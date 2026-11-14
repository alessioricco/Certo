"""Tests for model_reachability.py: no network, the server answers are faked."""

from __future__ import annotations

import pytest

from certo import model_reachability as mr
from certo.model_catalog import ModelCatalogEntry


@pytest.fixture(autouse=True)
def _fresh_cache():
    mr.clear_cache()
    yield
    mr.clear_cache()


def _entry(model: str, base_url: str | None = None) -> ModelCatalogEntry:
    return ModelCatalogEntry(name="m", model=model, base_url=base_url)


def _tags(monkeypatch, models: list[str] | None, calls: list[str] | None = None):
    def fake_get(url, timeout):
        if calls is not None:
            calls.append(url)
        if models is None:
            raise OSError("connection refused")
        return {"models": [{"name": m, "model": m} for m in models]}

    monkeypatch.setattr(mr, "_get", fake_get)


def test_a_cloud_model_is_never_asked(monkeypatch):
    calls: list[str] = []
    _tags(monkeypatch, None, calls)

    assert mr.unreachable_reason(_entry("anthropic/claude-haiku-5-5")) is None
    assert calls == []


def test_an_ollama_model_the_server_has_is_reachable(monkeypatch):
    calls: list[str] = []
    _tags(monkeypatch, ["qwen3.8:27b"], calls)

    entry = _entry("ollama/qwen3.8:27b", "http://turing.local:11434")

    assert mr.unreachable_reason(entry) is None
    assert calls == ["http://turing.local:11434/api/tags"]


def test_an_ollama_server_that_does_not_answer_is_named(monkeypatch):
    _tags(monkeypatch, None)

    why = mr.unreachable_reason(_entry("ollama/qwen3.8:27b", "http://turing.local:11434"))

    assert why == "the Ollama server at turing.local:11434 didn't answer"


def test_a_model_the_server_does_not_have_says_how_to_get_it(monkeypatch):
    _tags(monkeypatch, ["llama3:latest"])

    why = mr.unreachable_reason(_entry("ollama/qwen3.8:27b"))

    assert why == (
        "the Ollama server at localhost:11434 doesn't have qwen3.8:27b (ollama pull qwen3.8:27b)"
    )


def test_an_untagged_name_matches_latest(monkeypatch):
    _tags(monkeypatch, ["llama3:latest"])

    assert mr.unreachable_reason(_entry("ollama/llama3")) is None


def test_one_server_is_asked_once_for_several_models(monkeypatch):
    calls: list[str] = []
    _tags(monkeypatch, ["a:1", "b:2"], calls)

    mr.unreachable_reason(_entry("ollama/a:1", "http://box:11434"))
    mr.unreachable_reason(_entry("ollama/b:2", "http://box:11434"))

    assert len(calls) == 1


def test_another_local_server_is_asked_by_its_port(monkeypatch):
    def refuse(address, timeout):
        assert address == ("127.0.0.1", 1234)
        raise OSError("refused")

    monkeypatch.setattr(mr.socket, "create_connection", refuse)

    why = mr.unreachable_reason(_entry("lm_studio/some-model", "http://127.0.0.1:1234/v1"))

    assert why == "nothing answered at 127.0.0.1:1234"


def test_a_local_model_with_no_address_is_not_asked(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("should not connect")

    monkeypatch.setattr(mr.socket, "create_connection", fail)

    assert mr.unreachable_reason(_entry("lm_studio/some-model")) is None
