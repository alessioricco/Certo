"""Tests for certo.llm.build_llm — no network, no real API key needed.

Focus: cfg.reasoning_effort's pass-through. The SDK's own
`LLM.reasoning_effort` field defaults to "high", and an explicit None is a
distinct value meaning "send no reasoning parameter" (see
`_reasoning_effort_kwargs`). "none"/"off" and an unconfigured Ollama model
must end up as None; everything else keeps the old pass-through.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from openhands.sdk import Message, TextContent

from certo.config import load_config, override_llm
from certo.llm import build_llm


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "CERTO_LLM_MODEL": "anthropic/claude-sonnet-4-5-20250929",
        "CERTO_LLM_API_KEY": "sk-test",
    }
    env.update(overrides)
    return env


def test_build_llm_without_reasoning_effort_uses_sdk_default():
    cfg = load_config(_base_env())
    assert cfg.reasoning_effort is None

    llm = build_llm(cfg)

    assert llm.reasoning_effort == "high"


def test_build_llm_with_reasoning_effort_overrides_sdk_default():
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT="low"))

    llm = build_llm(cfg)

    assert llm.reasoning_effort == "low"


def test_build_llm_passes_through_model_and_base_url():
    cfg = load_config(_base_env(CERTO_LLM_BASE_URL="http://localhost:11434"))

    llm = build_llm(cfg)

    assert llm.model == "anthropic/claude-sonnet-4-5-20250929"
    assert llm.base_url == "http://localhost:11434"


def test_build_llm_usage_id_defaults_to_certo():
    cfg = load_config(_base_env())

    llm = build_llm(cfg)

    assert llm.usage_id == "certo"


def test_build_llm_usage_id_is_overridable():
    # Auto model selection (model_selection.py) gives each catalog candidate
    # its own usage_id so the SDK's LLM registry never confuses one
    # candidate's config for another's on a mid-task switch_llm() call.
    cfg = load_config(_base_env())

    llm = build_llm(cfg, usage_id="certo:deep-reasoner")

    assert llm.usage_id == "certo:deep-reasoner"


@pytest.mark.parametrize("value", ["none", "off", "OFF", " None "])
def test_build_llm_reasoning_off_passes_explicit_none(value):
    cfg = load_config(_base_env(CERTO_LLM_REASONING_EFFORT=value))

    llm = build_llm(cfg)

    assert llm.reasoning_effort is None


def test_build_llm_reasoning_off_via_override_passes_explicit_none():
    cfg = override_llm(
        load_config(_base_env(CERTO_LLM_REASONING_EFFORT="high")), reasoning_effort="off"
    )

    assert build_llm(cfg).reasoning_effort is None


@pytest.mark.parametrize("model", ["ollama/qwen3-coder:30b", "ollama_chat/qwen3-coder:30b"])
def test_build_llm_ollama_without_reasoning_effort_does_not_inherit_high(model):
    cfg = load_config({"CERTO_LLM_MODEL": model, "CERTO_LLM_BASE_URL": "http://localhost:11434"})

    assert build_llm(cfg).reasoning_effort is None


def test_build_llm_ollama_explicit_reasoning_effort_still_applies():
    # A thinking-capable Ollama model (qwen3, deepseek-r1) can opt back in.
    cfg = load_config(
        {
            "CERTO_LLM_MODEL": "ollama/qwen3:8b",
            "CERTO_LLM_BASE_URL": "http://localhost:11434",
            "CERTO_LLM_REASONING_EFFORT": "high",
        }
    )

    assert build_llm(cfg).reasoning_effort == "high"


class _FakeOllama(BaseHTTPRequestHandler):
    """Answers like an Ollama server hosting a model with no thinking mode:
    any request asking for thinking gets Ollama's real 400."""

    bodies: ClassVar[list[dict]] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        self.bodies.append(body)
        if body.get("think"):
            self._send(400, {"error": f'"{body.get("model")}" does not support thinking'})
        elif self.path == "/api/show":
            self._send(200, {"model_info": {"general.architecture": "qwen3"}, "capabilities": []})
        else:
            done = {"done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}
            reply = {"message": {"role": "assistant", "content": "pong"}}
            if self.path != "/api/chat":
                reply = {"response": "pong"}
            self._send(
                200,
                {"model": body.get("model"), "created_at": "2026-01-01T00:00:00Z", **reply, **done},
            )

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_ollama_url():
    _FakeOllama.bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("model", ["ollama/qwen3-coder:30b", "ollama_chat/qwen3-coder:30b"])
@pytest.mark.parametrize("effort", [None, "none", "off"])
def test_ollama_request_never_asks_for_thinking(fake_ollama_url, model, effort):
    # End to end through the SDK and LiteLLM, against a local fake server:
    # the README quickstart model must not be sent `think`.
    env = {"CERTO_LLM_MODEL": model, "CERTO_LLM_BASE_URL": fake_ollama_url}
    if effort is not None:
        env["CERTO_LLM_REASONING_EFFORT"] = effort
    llm = build_llm(load_config(env)).model_copy(update={"num_retries": 0})

    llm.completion([Message(role="user", content=[TextContent(text="ping")])])

    assert _FakeOllama.bodies
    assert all("think" not in body for body in _FakeOllama.bodies)


def test_build_llm_uses_the_configured_timeout():
    assert build_llm(load_config(_base_env())).timeout == 300
    assert build_llm(load_config(_base_env(CERTO_LLM_TIMEOUT_SECONDS="1200"))).timeout == 1200


def test_build_llm_timeout_zero_means_no_limit():
    assert build_llm(load_config(_base_env(CERTO_LLM_TIMEOUT_SECONDS="0"))).timeout is None


# --- The context window (context_window.py) ------------------------------


def test_a_set_context_window_reaches_the_sdk_and_ollama():
    cfg = load_config(
        _base_env(CERTO_LLM_MODEL="ollama/qwen3.8:27b", CERTO_LLM_CONTEXT_TOKENS="32768")
    )

    llm = build_llm(cfg)

    assert llm.max_input_tokens == 24576
    assert llm.litellm_extra_body == {"options": {"num_ctx": 32768}}


def test_a_cloud_model_with_a_set_window_sends_no_num_ctx():
    llm = build_llm(load_config(_base_env(CERTO_LLM_CONTEXT_TOKENS="65536")))

    assert llm.max_input_tokens == 49152
    assert not llm.litellm_extra_body


def test_ollamas_own_window_is_used_when_none_is_set(monkeypatch):
    monkeypatch.setattr("certo.llm.ollama_context_tokens", lambda *a, **k: 131072)

    llm = build_llm(load_config(_base_env(CERTO_LLM_MODEL="ollama/qwen3.8:27b")))

    assert llm.max_input_tokens == 98304
    assert not llm.litellm_extra_body  # the server's own size, nothing to ask for


def test_a_window_below_the_minimum_is_refused_with_the_fix(monkeypatch):
    from openhands.sdk.llm.exceptions import LLMContextWindowTooSmallError

    monkeypatch.setattr("certo.llm.ollama_context_tokens", lambda *a, **k: 4096)

    with pytest.raises(LLMContextWindowTooSmallError, match="CERTO_LLM_CONTEXT_TOKENS=32768"):
        build_llm(load_config(_base_env(CERTO_LLM_MODEL="ollama/qwen3.8:27b")))


@pytest.mark.parametrize("effort", ["", "none", "low", "high", "max"])
@pytest.mark.parametrize(
    "model",
    ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5"],
)
def test_claude_requests_carry_no_sampling_parameters(monkeypatch, model, effort):
    # Anthropic's API version 2026-10-21 refuses temperature, top_p and
    # top_k (checked live 2026-11-08: "Extra inputs are not permitted").
    # Today's SDK drops them for Claude; this catches an upgrade that
    # starts sending them. The request is captured before it leaves.
    import httpx

    sent: list[httpx.Request] = []

    class Captured(Exception):
        pass

    def capture(self, request, *args, **kwargs):
        sent.append(request)
        raise Captured

    monkeypatch.setattr(httpx.Client, "send", capture)
    cfg = override_llm(
        load_config({"CERTO_LLM_MODEL": model, "CERTO_LLM_API_KEY": "test-key"}),
        reasoning_effort=effort,
    )
    llm = build_llm(cfg)
    llm.num_retries = 0
    with pytest.raises(Exception):  # noqa: B017 - the capture stops every call
        llm.completion([Message(role="user", content=[TextContent(text="hi")])])

    assert sent, "no request reached the HTTP client"
    body = json.loads(sent[-1].content)
    assert not {"temperature", "top_p", "top_k"} & body.keys()
