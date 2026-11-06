"""How much a model can see at once, and how much of it the conversation
may fill before the SDK's condenser summarizes older steps (agent.py).

The SDK learns a context window from LiteLLM, which knows cloud models but
returns nothing for an Ollama model. An Ollama server also cuts a prompt
longer than its window without an error, so the model silently loses the
start of the task. So for an Ollama model Certo asks the server: it loads
the model (the run would load it anyway) and reads the window it got from
`/api/ps`. `CERTO_LLM_CONTEXT_TOKENS` (or `context_tokens` in models.yaml)
sets the window instead; for Ollama, Certo then asks the server for that
size (`num_ctx`, llm.py).

Stdlib only, no SDK import.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# The SDK refuses a smaller window (its MIN_CONTEXT_WINDOW_TOKENS).
MIN_CONTEXT_TOKENS = 16384
# Room kept for the model's answer: Ollama's window holds both.
_MIN_OUTPUT_RESERVE = 4096
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_OLLAMA_PREFIXES = ("ollama/", "ollama_chat/")
# A server's window only changes when it restarts.
_CACHE_SECONDS = 600

_cache: dict[tuple[str, str], tuple[float, int | None]] = {}
_lock = threading.Lock()


def is_ollama(model: str) -> bool:
    return model.startswith(_OLLAMA_PREFIXES)


def input_limit(context_tokens: int) -> int:
    """How many tokens the conversation may hold before it is condensed:
    the window less a reserve for the answer (a quarter, at least 4,096),
    never under the SDK's minimum."""
    reserve = max(_MIN_OUTPUT_RESERVE, context_tokens // 4)
    return max(MIN_CONTEXT_TOKENS, context_tokens - reserve)


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _get(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def ollama_context_tokens(model: str, base_url: str | None, timeout: float) -> int | None:
    """The window an Ollama server gives `model` (a LiteLLM name such as
    `ollama/qwen3.8:27b`), or None when it can't be learned. Loads the
    model first: `/api/ps` lists only loaded models."""
    name = model.split("/", 1)[1]
    base = (base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
    key = (base, name)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_SECONDS:
            return cached[1]
    tokens = None
    try:
        # An empty request loads the model and returns once it is ready.
        _post(f"{base}/api/generate", {"model": name}, timeout)
        for loaded in _get(f"{base}/api/ps", 10).get("models", []):
            if loaded.get("name") == name or loaded.get("model") == name:
                value = loaded.get("context_length")
                tokens = value if isinstance(value, int) and value > 0 else None
                break
    except (OSError, ValueError, urllib.error.URLError):
        logger.warning("Could not read the context window of %s from Ollama", model, exc_info=True)
    with _lock:
        _cache[key] = (time.monotonic(), tokens)
    return tokens


def ollama_version(base_url: str | None, timeout: float = 10) -> str | None:
    """The Ollama server's version (`/api/version`), or None when it doesn't
    answer."""
    base = (base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
    try:
        version = _get(f"{base}/api/version", timeout).get("version")
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return None
    return version if isinstance(version, str) and version else None


def ollama_model_digest(model: str, base_url: str | None, timeout: float = 10) -> str | None:
    """The digest of the build of `model` (a LiteLLM name such as
    `ollama/qwen3.8:27b`) the server has (`/api/tags`), or None when it
    can't be learned. Two benchmarks with the same model name can then be
    told apart when the model was pulled again in between. Doesn't load
    the model."""
    name = model.split("/", 1)[1]
    base = (base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
    try:
        for found in _get(f"{base}/api/tags", timeout).get("models", []):
            if name in (found.get("name"), found.get("model")):
                digest = found.get("digest")
                return digest if isinstance(digest, str) and digest else None
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return None
    return None


def ollama_capabilities(model: str, base_url: str | None, timeout: float = 10) -> list[str] | None:
    """What the server says `model` can do (`/api/show`), such as
    `tools` and `thinking`, or None when it can't be learned (a model it
    doesn't have, an old server, no answer). Doesn't load the model."""
    name = model.split("/", 1)[1]
    base = (base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
    try:
        found = _post(f"{base}/api/show", {"model": name}, timeout).get("capabilities")
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return None
    if not isinstance(found, list):
        return None
    return [c for c in found if isinstance(c, str)]


def server_address(base_url: str | None) -> str:
    """Host and port only: no scheme, path or credentials."""
    parsed = urllib.parse.urlsplit(base_url or _DEFAULT_OLLAMA_URL)
    try:
        port = parsed.port
    except ValueError:
        port = None
    host = parsed.hostname or "unknown"
    return f"{host}:{port}" if port else host


def _where(configured: bool) -> str:
    return "CERTO_LLM_CONTEXT_TOKENS" if configured else "the Ollama server's setting"


def _fix(model: str, size: int = 32768) -> str:
    if is_ollama(model):
        return (
            f"Set CERTO_LLM_CONTEXT_TOKENS={size} (Certo then asks Ollama for that size), or "
            f"start Ollama with OLLAMA_CONTEXT_LENGTH={size}."
        )
    return "Choose a model with a larger window, or set CERTO_LLM_CONTEXT_TOKENS."


def too_small_message(model: str, context_tokens: int, configured: bool) -> str:
    return (
        f"{model} has a context window of {context_tokens:,} tokens ({_where(configured)}), "
        f"below the {MIN_CONTEXT_TOKENS:,} an agent needs: the model would lose the start of "
        f"the task. {_fix(model)}"
    )


def known_context_tokens(
    model: str, configured: int, base_url: str | None, timeout: float
) -> int | None:
    """The model's context window when Certo knows it: the configured one,
    or for Ollama the server's (cached, so asking again before the run
    costs nothing). None for a cloud model without a configured window:
    LiteLLM knows those, and they are far larger."""
    if configured:
        return configured
    if is_ollama(model):
        return ollama_context_tokens(model, base_url, timeout)
    return None


def small_window_warning(
    model: str, context_tokens: int, warn_at: int, configured: bool, condense: bool
) -> str:
    """The notice for a window under CERTO_CONTEXT_WARN_TOKENS. The run
    still starts: only a window under the SDK's minimum is refused."""
    effect = (
        "when a long task fills it, older steps are summarized and the run goes on"
        if condense
        else "a long task may fill it, and with CERTO_CONDENSE=no nothing makes room"
    )
    fix = (
        _fix(model, max(warn_at, 32768))
        if is_ollama(model)
        # A cloud model's window is only known when CERTO_LLM_CONTEXT_TOKENS sets it.
        else "Raise CERTO_LLM_CONTEXT_TOKENS if the model allows more, or choose a model "
        "with a larger window."
    )
    return (
        f"{model} has a context window of {context_tokens:,} tokens ({_where(configured)}), "
        f"under CERTO_CONTEXT_WARN_TOKENS={warn_at:,}: {effect}. For more room, "
        f"{fix[0].lower()}{fix[1:]} (CERTO_CONTEXT_WARN_TOKENS=0 turns this warning off.)"
    )
