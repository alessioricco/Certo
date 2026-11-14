"""Whether a local model can be reached before `--auto-model` gives it work.

A local model's server (Ollama on this machine or another one on the
network) can be switched off; a run on it then fails only after the
provider's retries, minutes later. So before a local candidate is used,
Certo asks its server, in a few seconds: is it up, and does it have the
model? Cloud models aren't asked: an unreachable provider, a bad key or
no credit fails at once, and asking would be a paid call.

Stdlib only, no SDK import. Never reads or prints a key.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.parse

from .context_window import _DEFAULT_OLLAMA_URL, _get, is_ollama, server_address
from .model_catalog import ModelCatalogEntry
from .model_pricing import is_local

PROBE_TIMEOUT_SECONDS = 5.0
# A run can probe the same server several times (each milestone, each
# fallback); one answer is good for this long.
_CACHE_SECONDS = 30.0

_cache: dict[str, tuple[float, frozenset[str] | None]] = {}
_lock = threading.Lock()


def _ollama_models(base: str, timeout: float) -> frozenset[str] | None:
    """The model names an Ollama server has, or None when it doesn't answer."""
    with _lock:
        cached = _cache.get(base)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_SECONDS:
            return cached[1]
    try:
        found = _get(f"{base}/api/tags", timeout).get("models", [])
        names = frozenset(
            str(n)
            for m in found
            if isinstance(m, dict)
            for n in (m.get("name"), m.get("model"))
            if n
        )
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        names = None
    with _lock:
        _cache[base] = (time.monotonic(), names)
    return names


def _port_open(base_url: str, timeout: float) -> bool:
    parsed = urllib.parse.urlsplit(base_url)
    if not parsed.hostname:
        return True  # nothing to ask: let the run find out
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return True  # a malformed port: let the run report it
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


def unreachable_reason(
    entry: ModelCatalogEntry, timeout: float = PROBE_TIMEOUT_SECONDS
) -> str | None:
    """Why `entry` can't be used right now, or None when it can (or when
    there is nothing to ask: a cloud model, or a local one with no address)."""
    if not is_local(entry):
        return None
    where = server_address(entry.base_url)
    if is_ollama(entry.model):
        base = (entry.base_url or _DEFAULT_OLLAMA_URL).rstrip("/")
        names = _ollama_models(base, timeout)
        if names is None:
            return f"the Ollama server at {where} didn't answer"
        name = entry.model.split("/", 1)[1]
        if name in names or (":" not in name and f"{name}:latest" in names):
            return None
        return f"the Ollama server at {where} doesn't have {name} (ollama pull {name})"
    if not entry.base_url:
        return None
    if _port_open(entry.base_url, timeout):
        return None
    return f"nothing answered at {where}"


def clear_cache() -> None:
    """Forget the servers' answers (tests)."""
    with _lock:
        _cache.clear()
