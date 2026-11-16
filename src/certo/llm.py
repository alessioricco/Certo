"""Builds the SDK's LLM object from our Config.

The model-agnostic invariant lives in config.py: provider/model selection is
entirely a function of `cfg.model`'s LiteLLM-style prefix (e.g. "anthropic/...",
"openai/...", "ollama/..."). The one provider-aware choice here is the
*default* reasoning effort for Ollama (see `_reasoning_effort_kwargs`); it
never changes which provider or model is called.
"""

from __future__ import annotations

from openhands.sdk import LLM
from pydantic import SecretStr

from .config import Config
from .context_window import (
    MIN_CONTEXT_TOKENS,
    input_limit,
    is_ollama,
    ollama_context_tokens,
    too_small_message,
)

# LiteLLM prefixes that route to an Ollama server.
_OLLAMA_PREFIXES = {"ollama", "ollama_chat"}


def _reasoning_effort_kwargs(cfg: Config) -> dict[str, str | None]:
    """The `reasoning_effort` kwarg for `LLM(...)`, or nothing.

    The SDK's own field defaults to "high", and `reasoning_effort=None` is a
    distinct, accepted value meaning "send no reasoning parameter" (its
    chat options skip it when None). So:

    - "none" (config folds "off" into it): pass an explicit None. Passing
      the string "none" through would still reach an Ollama model as
      `think: false`.
    - any other configured value: pass it through unchanged.
    - unset, Ollama model: pass None. LiteLLM turns "high" into
      `think: true`, and Ollama rejects that outright for a model with no
      thinking mode ("... does not support thinking"), failing the very
      first call. A thinking-capable Ollama model can still opt in with
      CERTO_LLM_REASONING_EFFORT.
    - unset, anything else: omit the kwarg so the SDK's "high" applies.
    """
    effort = cfg.reasoning_effort
    if effort == "none":
        return {"reasoning_effort": None}
    if effort:
        return {"reasoning_effort": effort}
    if cfg.model.split("/", 1)[0].lower() in _OLLAMA_PREFIXES:
        return {"reasoning_effort": None}
    return {}


def _context_kwargs(cfg: Config) -> dict[str, object]:
    """The SDK's `max_input_tokens` (when the condenser summarizes older
    steps) from the model's context window, and for Ollama a set window
    requested as `num_ctx` (verified live: the server loads the model with
    it). Ollama's own window is asked from the server when nothing is set;
    other providers keep what LiteLLM reports. See context_window.py."""
    from openhands.sdk.llm.exceptions import LLMContextWindowTooSmallError

    configured = cfg.llm_context_tokens
    tokens = configured
    if not tokens and is_ollama(cfg.model):
        tokens = ollama_context_tokens(cfg.model, cfg.base_url, cfg.llm_timeout_seconds or 600)
    if not tokens:
        return {}
    if tokens < MIN_CONTEXT_TOKENS:
        raise LLMContextWindowTooSmallError(
            tokens, MIN_CONTEXT_TOKENS, too_small_message(cfg.model, tokens, bool(configured))
        )
    kwargs: dict[str, object] = {"max_input_tokens": input_limit(tokens)}
    if configured and is_ollama(cfg.model):
        kwargs["litellm_extra_body"] = {"options": {"num_ctx": configured}}
    return kwargs


def build_llm(cfg: Config, *, usage_id: str = "certo") -> LLM:
    return LLM(
        usage_id=usage_id,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=SecretStr(cfg.api_key) if cfg.api_key else None,
        # 0 means no limit, which the SDK spells None.
        timeout=cfg.llm_timeout_seconds or None,
        **_reasoning_effort_kwargs(cfg),
        **_context_kwargs(cfg),
    )


def complete_once(cfg: Config, prompt: str, *, usage_id: str) -> tuple[str, float]:
    """One call to `cfg`'s model outside the agent loop (the milestone
    planner, `certo ask`): the reply's text and its cost in US dollars."""
    from openhands.sdk import Message, TextContent

    llm = build_llm(cfg, usage_id=usage_id)
    response = llm.completion(messages=[Message(role="user", content=[TextContent(text=prompt)])])
    reply = "\n".join(
        text for content in response.message.content if (text := getattr(content, "text", None))
    )
    return reply, response.metrics.accumulated_cost or 0.0
