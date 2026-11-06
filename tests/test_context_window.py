import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from certo import context_window as cw


def test_input_limit_keeps_a_reserve_for_the_answer():
    assert cw.input_limit(131072) == 98304
    assert cw.input_limit(32768) == 24576
    assert cw.input_limit(20000) == 16384  # never under the SDK's minimum


def test_is_ollama():
    assert cw.is_ollama("ollama/qwen3.8:27b") and cw.is_ollama("ollama_chat/x")
    assert not cw.is_ollama("anthropic/claude-haiku-5-5")


class _FakeOllama(BaseHTTPRequestHandler):
    loaded: list = []

    def log_message(self, *_args):
        pass

    def _reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            if body["model"] != "qwen3.8:27b":
                self.send_error(404)
                return
            self._reply({"capabilities": ["completion", "tools", "thinking"]})
            return
        type(self).loaded.append(body["model"])
        self._reply({"done": True, "done_reason": "load"})

    def do_GET(self):
        if self.path == "/api/version":
            self._reply({"version": "0.12.6"})
            return
        if self.path == "/api/tags":
            self._reply({"models": [{"name": "qwen3.8:27b", "digest": "a1b2c3d4e5f6a7b8"}]})
            return
        models = [{"name": m, "model": m, "context_length": 32768} for m in type(self).loaded]
        self._reply({"models": models})


@pytest.fixture
def fake_ollama(monkeypatch):
    _FakeOllama.loaded = []
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_the_window_is_read_from_ollama_after_loading_the_model(fake_ollama):
    from importlib import reload

    fresh = reload(cw)  # the real function, not conftest's stub
    try:
        assert fresh.ollama_context_tokens("ollama/qwen3.8:27b", fake_ollama, 5) == 32768
        assert _FakeOllama.loaded == ["qwen3.8:27b"]
        fresh.ollama_context_tokens("ollama/qwen3.8:27b", fake_ollama, 5)
        assert _FakeOllama.loaded == ["qwen3.8:27b"]  # cached
    finally:
        reload(cw)


def test_an_unreachable_server_gives_none():
    from importlib import reload

    fresh = reload(cw)
    try:
        assert fresh.ollama_context_tokens("ollama/x", "http://127.0.0.1:9", 2) is None
    finally:
        reload(cw)


def test_the_version_is_read_from_ollama(fake_ollama):
    from importlib import reload

    fresh = reload(cw)
    try:
        assert fresh.ollama_version(fake_ollama) == "0.12.6"
        assert fresh.ollama_version("http://127.0.0.1:9", 2) is None
    finally:
        reload(cw)


def test_the_model_digest_is_read_from_ollama_without_loading_it(fake_ollama):
    from importlib import reload

    fresh = reload(cw)
    try:
        assert fresh.ollama_model_digest("ollama/qwen3.8:27b", fake_ollama) == "a1b2c3d4e5f6a7b8"
        assert fresh.ollama_model_digest("ollama/not-pulled", fake_ollama) is None
        assert fresh.ollama_model_digest("ollama/x", "http://127.0.0.1:9", 2) is None
        assert _FakeOllama.loaded == []
    finally:
        reload(cw)


def test_server_address_is_host_and_port_only():
    assert cw.server_address("http://user:secret@gpu-box:11434/v1") == "gpu-box:11434"
    assert cw.server_address(None) == "localhost:11434"
    assert cw.server_address("https://ollama.example.com") == "ollama.example.com"


def test_the_known_window_is_the_set_one_or_the_ollama_servers(monkeypatch):
    asked = []
    monkeypatch.setattr(cw, "ollama_context_tokens", lambda *a: asked.append(a) or 8192)
    assert cw.known_context_tokens("ollama/q", 32768, None, 5) == 32768
    assert cw.known_context_tokens("ollama/q", 0, "http://box:11434", 5) == 8192
    assert cw.known_context_tokens("anthropic/claude-haiku-5-5", 0, None, 5) is None
    assert asked == [("ollama/q", "http://box:11434", 5)]  # never for a cloud model


def test_the_small_window_warning_says_what_happens_and_how_to_fix_it():
    text = cw.small_window_warning("ollama/q", 24576, 32768, configured=False, condense=True)
    assert text.startswith(
        "ollama/q has a context window of 24,576 tokens (the Ollama server's setting), "
        "under CERTO_CONTEXT_WARN_TOKENS=32,768: when a long task fills it, older steps are "
        "summarized and the run goes on."
    )
    assert "CERTO_LLM_CONTEXT_TOKENS=32768" in text and "OLLAMA_CONTEXT_LENGTH=32768" in text
    assert "CERTO_CONTEXT_WARN_TOKENS=0 turns this warning off" in text
    raw = cw.small_window_warning("ollama/q", 24576, 65536, configured=True, condense=False)
    assert "(CERTO_LLM_CONTEXT_TOKENS)" in raw and "nothing makes room" in raw
    assert "CERTO_LLM_CONTEXT_TOKENS=65536" in raw
    cloud = cw.small_window_warning("anthropic/m", 20000, 32768, configured=True, condense=True)
    assert "For more room, raise CERTO_LLM_CONTEXT_TOKENS if the model allows more" in cloud


def test_the_capabilities_are_read_from_ollama_without_loading_it(fake_ollama):
    from importlib import reload

    fresh = reload(cw)
    try:
        assert fresh.ollama_capabilities("ollama/qwen3.8:27b", fake_ollama) == [
            "completion",
            "tools",
            "thinking",
        ]
        assert fresh.ollama_capabilities("ollama/not-pulled", fake_ollama) is None
        assert fresh.ollama_capabilities("ollama/x", "http://127.0.0.1:9", 2) is None
        assert _FakeOllama.loaded == []
    finally:
        reload(cw)
