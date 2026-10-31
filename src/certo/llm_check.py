"""Connectivity check for the configured LLM: one tiny, direct completion.

Used by `certo-admin check-llm`, and in its tool-calling form
(`check_tool_calling`) by `certo init` and `certo check`. Builds the model exactly as a real run
does (`llm.build_llm`, so `CERTO_LLM_MODEL`/`CERTO_LLM_API_KEY`/`CERTO_LLM_BASE_URL`/
`CERTO_LLM_REASONING_EFFORT` and any per-call override apply unchanged), but with
retries disabled and a short timeout: a health check should fail fast and
say why, not sit through the SDK's default 5 retries with up to 64s waits.

Passes only when the model returns non-empty text. Never prints the API key:
provider error text is scrubbed of it before being returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from . import context_window
from litellm.exceptions import NotFoundError as LiteLLMNotFoundError
from openhands.sdk import Message, TextContent
from openhands.sdk.agent.utils import make_llm_completion
from openhands.sdk.llm.exceptions.types import (
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)
from openhands.sdk.tool.builtins import FinishTool

from .config import Config
from .llm import build_llm

CHECK_PROMPT = "This is a connectivity check. Reply with exactly: OK"
TOOL_CHECK_PROMPT = (
    "This is a connectivity check. Do not reply with text: call the finish tool "
    "with the message OK."
)
DEFAULT_TIMEOUT_SECONDS = 60

# (exception type, short kind, actionable hint) — checked in order.
_ERROR_HINTS: tuple[tuple[type[Exception], str, str], ...] = (
    (
        LLMAuthenticationError,
        "authentication",
        (
            "The provider rejected the credentials — check CERTO_LLM_API_KEY matches "
            "the provider in CERTO_LLM_MODEL's prefix."
        ),
    ),
    (
        LLMRateLimitError,
        "rate_limit",
        "The provider is rate-limiting or the account is out of quota/credit.",
    ),
    (
        LLMTimeoutError,
        "timeout",
        (
            "No answer within the timeout — check CERTO_LLM_BASE_URL / network, or "
            "retry with a larger --timeout."
        ),
    ),
    (
        LLMServiceUnavailableError,
        "unavailable",
        (
            "The provider/endpoint is unreachable or down — check CERTO_LLM_BASE_URL "
            "and that a local server (e.g. Ollama) is running."
        ),
    ),
    (
        # Not mapped by the SDK: a direct completion() lets LiteLLM's own
        # NotFoundError through (confirmed live with an unknown model id).
        LiteLLMNotFoundError,
        "model_not_found",
        (
            "The provider doesn't know this model id, or the key has no access "
            "to it — check the spelling in CERTO_LLM_MODEL against the provider's "
            "current model list."
        ),
    ),
    (
        LLMBadRequestError,
        "bad_request",
        (
            "The request was rejected — often an unknown model id or an option "
            "the model doesn't support (e.g. CERTO_LLM_REASONING_EFFORT)."
        ),
    ),
)


_SETUP_HINT = (
    "The SDK rejected this model configuration before sending any request; "
    "a real run would fail the same way."
)


class _SetupError(Exception):
    """Marks a failure while building the LLM object, not while calling it."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


@dataclass(frozen=True)
class LLMCheckResult:
    ok: bool
    model: str
    base_url: str | None
    latency_seconds: float
    reply: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    # a kind from _ERROR_HINTS, else "setup" / "no_reply" / "error"
    error_kind: str | None = None
    error: str | None = None
    hint: str | None = None
    # Ollama-only; None for every cloud model (nothing changes for them).
    ollama_version: str | None = None
    context_tokens: int | None = None
    # "CERTO_LLM_CONTEXT_TOKENS" or "server" — where context_tokens came from.
    context_source: str | None = None
    tokens_per_second: float | None = None
    context_warning: str | None = None  # the run's own warning text, if any


def _scrub(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text


def _build_check_llm(cfg: Config, timeout: int):
    # Called inside the caller's try: the SDK validates some settings when
    # the LLM object is *built* (e.g. it rejects a context window below its
    # 16K minimum, confirmed live with ollama/llama3), before any request is
    # sent. The same error would stop a real run, so it's a check failure too.
    try:
        return build_llm(cfg, usage_id="check-llm").model_copy(
            update={"num_retries": 0, "timeout": timeout}
        )
    except Exception as exc:
        raise _SetupError(exc) from exc


def _failure(cfg: Config, exc: Exception, started: float) -> LLMCheckResult:
    kind, hint = "error", None
    latency = time.monotonic() - started
    if isinstance(exc, _SetupError):
        exc = exc.original
        kind, hint = "setup", _SETUP_HINT
    for exc_type, exc_kind, exc_hint in _ERROR_HINTS:
        if isinstance(exc, exc_type):
            kind, hint = exc_kind, exc_hint
            break
    return LLMCheckResult(
        ok=False,
        model=cfg.model,
        base_url=cfg.base_url,
        latency_seconds=latency,
        **_ollama_details(cfg, timeout=5),
        error_kind=kind,
        error=_scrub(f"{type(exc).__name__}: {exc}", cfg.api_key),
        hint=hint,
    )


def _usage(response) -> dict:
    usage = response.metrics.accumulated_token_usage
    return {
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "cost": response.metrics.accumulated_cost,
    }


def check_llm(cfg: Config, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> LLMCheckResult:
    """Send `CHECK_PROMPT` once to the configured model and report the result."""
    started = time.monotonic()
    try:
        llm = _build_check_llm(cfg, timeout)
        response = llm.completion(
            messages=[Message(role="user", content=[TextContent(text=CHECK_PROMPT)])]
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reported result
        return _failure(cfg, exc, started)
    latency = time.monotonic() - started

    reply = " ".join(
        text.strip()
        for content in response.message.content
        if (text := getattr(content, "text", None)) and text.strip()
    )
    return LLMCheckResult(
        ok=bool(reply),
        model=cfg.model,
        base_url=cfg.base_url,
        latency_seconds=latency,
        reply=reply,
        **_usage(response),
        **_extra_details(cfg, response, latency),
        error_kind=None if reply else "no_reply",
        error=None if reply else "The model answered, but with no text content.",
        hint=None,
    )


def check_tool_calling(cfg: Config, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> LLMCheckResult:
    """One request offering the SDK's `finish` tool, sent through the same
    call the agent makes (`make_llm_completion`), so the request has the
    agent's shape: tool schema, Responses vs Chat Completions, and prompt-
    based tool calling for models without native support. Passes only when
    the model answers with a tool call, since the agent works only through
    tool calls."""
    started = time.monotonic()
    try:
        llm = _build_check_llm(cfg, timeout)
        response = make_llm_completion(
            llm,
            [Message(role="user", content=[TextContent(text=TOOL_CHECK_PROMPT)])],
            tools=list(FinishTool.create()),
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reported result
        return _failure(cfg, exc, started)
    calls = response.message.tool_calls or []
    reply = calls[0].name if calls else ""
    latency = time.monotonic() - started
    return LLMCheckResult(
        ok=bool(calls),
        model=cfg.model,
        base_url=cfg.base_url,
        latency_seconds=latency,
        reply=reply,
        **_usage(response),
        **_extra_details(cfg, response, latency),
        error_kind=None if calls else "no_tool_call",
        error=None if calls else "The model answered without calling a tool.",
        hint=None,
    )


_TOOLS_UNSUPPORTED = (
    "does not support tools",
    "tool use is not supported",
    "tools are not supported",
    "does not support function calling",
    "function calling is not",
    "tool_choice",
)
_NO_CREDIT = ("credit balance", "insufficient_quota", "exceeded your current quota", "billing")
_MODEL_UNKNOWN = ("model_not_found", "does not exist", "unknown model", "invalid model")


def explain(result: LLMCheckResult, provider: str | None = None) -> str:
    """One plain line for a beginner: either the ok line or what's wrong and
    how to fix it. `provider` is a display name (e.g. "Anthropic")."""
    if result.ok:
        return "ok: reachable, tool calling works."
    text = (result.error or "").lower()
    ollama = _is_ollama(result.model)
    name = result.model.split("/", 1)[-1]
    who = provider or "the provider"

    if any(s in text for s in _NO_CREDIT) or result.error_kind == "rate_limit":
        return (
            f"{who} refused the request: the account is out of credit, or it is "
            "being rate limited. Check your billing page, or wait a minute, then "
            "run certo check again."
        )
    if result.error_kind == "authentication":
        return (
            f"{who} rejected the API key. Check CERTO_LLM_API_KEY in your settings: it must "
            f"be a valid key for {who}, pasted with no spaces."
        )
    suggestion = " Models such as qwen3.8:27b support it." if ollama else ""
    if any(s in text for s in _TOOLS_UNSUPPORTED):
        return (
            f"The model {result.model} doesn't support tool calling, which Certo's "
            "agent needs. Choose another model in CERTO_LLM_MODEL in your settings." + suggestion
        )
    if result.error_kind == "no_tool_call":
        return (
            f"The model {result.model} answered, but without calling a tool. "
            "Certo's agent works only through tool calls, so choose a model that "
            "supports tool calling in CERTO_LLM_MODEL in your settings." + suggestion
        )
    model_unknown = result.error_kind == "model_not_found" or any(s in text for s in _MODEL_UNKNOWN)
    if ollama and "not found" in text and "model" in text:
        model_unknown = True
    if model_unknown:
        if ollama:
            return (
                f"Ollama has no model named {name}. Install it with: ollama pull "
                f"{name} (or pick an installed one, listed by: ollama list)."
            )
        return (
            f"{who} doesn't know the model {result.model}. Check the spelling of "
            "CERTO_LLM_MODEL in your settings against the provider's model list."
        )
    if result.error_kind in ("unavailable", "timeout"):
        if result.base_url:
            tip = (
                " If Ollama runs on another machine, start it there with OLLAMA_HOST=0.0.0.0."
                if ollama
                else ""
            )
            return (
                f"Couldn't reach the server at {result.base_url}. Check "
                f"CERTO_LLM_BASE_URL in your settings and that the server is running.{tip}"
            )
        return (
            f"Couldn't reach {who}. Check your internet connection; if it works, "
            "the provider may be having an outage, so try again in a few minutes."
        )
    if result.error_kind == "setup":
        return f"Certo can't use this model as configured: {result.error}"
    return f"The check failed: {result.error}"


def _is_ollama(model: str) -> bool:
    return model.split("/", 1)[0] in ("ollama", "ollama_chat")


def _ollama_details(cfg: Config, *, timeout: int | None = None) -> dict:
    """Version, effective context window (and its source), and the run's
    own small-window warning. Never raises: a check must still report
    the request result if the server can't answer this.

    `timeout` overrides the probe timeout; the failure path passes a
    short one (5s) so a down server can't stall a check that is supposed
    to fail fast. Without it, the caller's full model timeout is used."""
    if not _is_ollama(cfg.model):
        return {}
    t = timeout or (cfg.llm_timeout_seconds or 600)
    details: dict = {}
    try:
        details["ollama_version"] = context_window.ollama_version(cfg.base_url, t)
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        tokens = context_window.known_context_tokens(cfg.model, cfg.llm_context_tokens, cfg.base_url, t)
        source = "CERTO_LLM_CONTEXT_TOKENS" if cfg.llm_context_tokens else "server"
        if tokens:
            details["context_tokens"] = tokens
            details["context_source"] = source
            if cfg.context_warn_tokens and tokens < cfg.context_warn_tokens:
                details["context_warning"] = context_window.small_window_warning(
                    cfg.model,
                    tokens,
                    cfg.context_warn_tokens,
                    bool(cfg.llm_context_tokens),
                    cfg.condense,
                )
    except Exception:  # noqa: BLE001
        pass
    return details


def _extra_details(cfg: Config, response, latency: float) -> dict:
    """Kwargs to add on top of `_usage(response)`: the Ollama-only fields
    (empty for cloud models) and tokens/second when the response reports
    completion tokens. Never raises — a broken metrics read must not turn
    a passing check into a failure."""
    details = _ollama_details(cfg)
    try:
        usage = response.metrics.accumulated_token_usage
        if usage and usage.completion_tokens and latency > 0:
            details["tokens_per_second"] = usage.completion_tokens / latency
    except Exception:  # noqa: BLE001 - display-only
        pass
    return details


def detail_lines(result: LLMCheckResult) -> list[str]:
    """The extra context lines `certo check` prints for a local (Ollama)
    model: server version, the context window the run will use and where it
    came from, the test request's time and tokens/second, and — separately —
    the same small-window warning a run emits. Empty for cloud models, so
    their output is unchanged."""
    if not _is_ollama(result.model):
        return []
    parts: list[str] = []
    if result.ollama_version:
        parts.append(f"Ollama {result.ollama_version}")
    if result.context_tokens:
        window = f"context window {result.context_tokens:,} tokens"
        if result.context_source:
            window += f" (from {result.context_source})"
        parts.append(window)
    timing = f"{result.latency_seconds:.1f}s"
    if result.tokens_per_second:
        timing += f", {result.tokens_per_second:.1f} tok/s"
    parts.append(timing)
    lines = [" · ".join(parts)]
    if result.context_warning:
        lines.append(result.context_warning)
    return lines
