"""Tool calls a model wrote as text instead of making them.

Some local models (`qwen3.8:27b` in 25 of 151 saved benchmark runs,
`qwen3.6` and `devstral` in most) sometimes answer with a tool call as
JSON in a plain text message. The agent framework takes a text message
with no tool call as the final answer, so the run ends there, often on
its first step. No cloud model did it in 178 saved runs.

`looks_like_tool_call()` recognises such a message; the runner then
sends `REMINDER` and lets the agent go on (`CERTO_TOOL_CALL_REMINDERS`).
Pure text checks, no model and no SDK.

Shapes seen in saved transcripts, each as the whole message:

- the arguments alone: `{"command": "view", "path": "/..."}`;
- the tool named under a key: `{"tool_name": "terminal", "arguments":
  {...}}`, also `name`, `tool` or `tool_use`, or the arguments next to
  the name: `{"name": "file_editor", "command": "view", ...}`; also the
  name under `command` next to `arguments`: `{"command": "file_editor",
  "arguments": {...}}`;
- OpenAI's format: `{"type": "function", "function": {"name": ...}}`;
- the tool's name as the key: `{"task_tracker": {"task_list": [...]}}`;
- a tool-use or tool-result block of the model API, with no tool name:
  `{"type": "tool_result", "tool_use_id": "call_1", "content": "..."}`;
- any of these cut off mid-file, so the JSON doesn't parse.

JSON that names no tool and isn't one tool's arguments, such as
`{"thinking": "..."}`, is not a call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

REMINDER = (
    "Certo: your last message was a tool call written as plain text, so "
    "it did not run, and nothing happened. Make it as a real tool call "
    "(a function call), not as text, and go on with the task."
)

# Fields the agent framework adds to every tool's arguments, next to the
# tool's own.
_ALWAYS_ALLOWED = frozenset({"summary", "security_risk"})
# Keys a model puts the tool's name under.
_NAME_KEYS = ("name", "tool_name", "tool", "tool_use")
# `type` values of the model API's tool blocks, which a model sometimes
# writes as text.
_TOOL_BLOCK_TYPES = frozenset({"tool_use", "tool_result"})
# When the runner can't read the agent's tools: the built-in coding tools
# and their parameters (openhands-tools 1.47.0).
DEFAULT_TOOLS: Mapping[str, frozenset[str]] = {
    "terminal": frozenset({"command", "is_input", "reset", "timeout"}),
    "file_editor": frozenset(
        {"command", "file_text", "insert_line", "new_str", "old_str", "path", "view_range"}
    ),
    "task_tracker": frozenset({"command", "task_list"}),
}

_FENCE = re.compile(r"^```[\w-]*\s*|\s*```$")
_TAGS = re.compile(r"^<tool_call>\s*|\s*</tool_call>$")
_NAMED = re.compile(r'"(?:name|tool_name|tool|tool_use)"\s*:\s*"([^"]+)"')
_FIRST_KEY = re.compile(r'^\{\s*"([^"]+)"\s*:')


def looks_like_tool_call(text: str, tools: Mapping[str, Iterable[str]] | None = None) -> bool:
    """True when `text` is, as a whole, a tool call written as JSON.

    `tools` maps each of the agent's tool names to its parameter names
    (`DEFAULT_TOOLS` when not given). Prose, or JSON that isn't a call to
    one of these tools, is never a tool call."""
    body = _TAGS.sub("", _FENCE.sub("", text.strip())).strip()
    if not body.startswith("{"):
        return False
    known = {name: frozenset(p) for name, p in (tools or DEFAULT_TOOLS).items()}
    try:
        value = json.loads(body)
    except ValueError:
        return _cut_off_call(body, known)
    if not isinstance(value, dict) or not value:
        return False
    return (
        value.get("type") in _TOOL_BLOCK_TYPES
        or _names_tool(value, known)
        or any(k in known for k in value)
        or _bare_arguments(set(value), known)
    )


def _names_tool(value: dict, known: Mapping[str, frozenset[str]]) -> bool:
    """A known tool's name under one of `_NAME_KEYS`, at the top or inside
    a `function` or `tool_use` object."""
    for key in _NAME_KEYS:
        name = value.get(key)
        if isinstance(name, str) and name in known:
            return True
    if isinstance(value.get("arguments"), dict) and value.get("command") in known:
        return True
    return any(
        isinstance(value.get(key), dict) and _names_tool(value[key], known)
        for key in ("function", "tool_use")
    )


def _bare_arguments(keys: set[str], known: Mapping[str, frozenset[str]]) -> bool:
    """The arguments of one tool: every key is that tool's, and at least
    one is more than the framework's own fields."""
    own = keys - _ALWAYS_ALLOWED
    return bool(own) and any(own <= params for params in known.values())


def _cut_off_call(body: str, known: Mapping[str, frozenset[str]]) -> bool:
    """JSON that doesn't parse, most likely cut off by the output limit:
    a call by its start alone."""
    named = _NAMED.search(body[:300])
    if named and named.group(1) in known:
        return True
    first = _FIRST_KEY.match(body)
    if not first:
        return False
    key = first.group(1)
    return key in known or any(key in params for params in known.values())


# --- A turn that ends by announcing its next step ------------------------------------

NEXT_STEP_REMINDER = (
    "Certo: your last message said what you would do next, but made no tool "
    "call, so nothing ran and your turn ended. Make that tool call now and go "
    "on with the task. If the task is already done, say so in one line."
)

# Where a model that wrote its message as a JSON object put the words.
_TEXT_KEYS = ("text", "message", "thinking")
# "Now let me ...", "Next, I'll ...", "Let me ...", but not "let me know".
_NEXT_STEP = re.compile(
    r"\b(?:now|next|then)\b[,\s]*(?:let me|let's|i'll|i will|i'm going to)\b"
    r"|^(?:let me|let's|i'll|i will)\b(?!\s+know)",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def announces_next_step(text: str) -> bool:
    """True when the message ends by saying what the agent will do next
    ("Now let me add the save method."), as its whole last sentence, and so
    ends the turn with the work not done. The words may be plain text or
    inside a JSON object a model wrote as text (`{"type": "text", "text":
    "..."}`, also under `message` or `thinking`). Seen only on local models:
    in the saved benchmark runs, 4 local endings and none of 194 cloud
    ones."""
    words = text.strip()
    if words.startswith("{"):
        try:
            value = json.loads(words)
        except ValueError:
            return False
        if not isinstance(value, dict):
            return False
        found = [value[k] for k in _TEXT_KEYS if isinstance(value.get(k), str)]
        if not found:
            return False
        words = found[0].strip()
    sentences = [s for s in _SENTENCE_END.split(words) if s.strip()]
    return bool(sentences) and bool(_NEXT_STEP.search(sentences[-1].strip()))
