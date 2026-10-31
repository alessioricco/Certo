"""llm_check.py + `certo-admin check-llm` tests. No network: `build_llm`
is monkeypatched to return a fake LLM, so only result shaping, error
classification, secret scrubbing, and CLI output/exit codes are exercised.
(The real call path was verified live — see DECISIONS.md.)
"""

from __future__ import annotations

from types import SimpleNamespace
from certo import context_window
import pytest
from openhands.sdk import TextContent
from openhands.sdk.llm.exceptions.types import (
    LLMAuthenticationError,
    LLMContextWindowTooSmallError,
)

from certo import admin_cli, llm_check
from certo.config import Config

SECRET = "sk-super-secret-value"


def _cfg(**overrides) -> Config:
    base = {
        "model": "openai/gpt-4o",
        "api_key": SECRET,
        "base_url": None,
        "workspace": ".",
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


def _response(*texts, prompt=17, completion=4, cost=0.00001):
    return SimpleNamespace(
        message=SimpleNamespace(content=[TextContent(text=t) for t in texts]),
        metrics=SimpleNamespace(
            accumulated_token_usage=SimpleNamespace(
                prompt_tokens=prompt, completion_tokens=completion
            ),
            accumulated_cost=cost,
        ),
    )


class FakeLLM:
    def __init__(self, outcome):
        self.outcome = outcome
        self.copy_updates = None
        self.messages = None

    def model_copy(self, *, update):
        self.copy_updates = update
        return self

    def completion(self, *, messages):
        self.messages = messages
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _patch(monkeypatch, outcome) -> FakeLLM:
    fake = FakeLLM(outcome)
    monkeypatch.setattr(llm_check, "build_llm", lambda cfg, usage_id: fake)
    return fake


def test_successful_answer_reports_reply_tokens_and_cost(monkeypatch):
    fake = _patch(monkeypatch, _response("OK"))

    result = llm_check.check_llm(_cfg(), timeout=15)

    assert result.ok
    assert result.reply == "OK"
    assert (result.prompt_tokens, result.completion_tokens) == (17, 4)
    assert result.cost == 0.00001
    # Fail fast: no SDK retries, caller's timeout.
    assert fake.copy_updates == {"num_retries": 0, "timeout": 15}
    assert fake.messages[0].content[0].text == llm_check.CHECK_PROMPT


def test_answer_without_text_is_a_failure(monkeypatch):
    _patch(monkeypatch, _response("   "))

    result = llm_check.check_llm(_cfg())

    assert not result.ok
    assert result.error_kind == "no_reply"


def test_authentication_error_is_classified_with_a_hint_and_key_scrubbed(monkeypatch):
    _patch(monkeypatch, LLMAuthenticationError(f"Incorrect API key provided: {SECRET}"))

    result = llm_check.check_llm(_cfg())

    assert not result.ok
    assert result.error_kind == "authentication"
    assert "CERTO_LLM_API_KEY" in result.hint
    assert SECRET not in result.error
    assert "***" in result.error


def test_unmapped_error_is_reported_not_raised(monkeypatch):
    _patch(monkeypatch, RuntimeError("something odd"))

    result = llm_check.check_llm(_cfg())

    assert (result.ok, result.error_kind, result.hint) == (False, "error", None)
    assert "RuntimeError: something odd" in result.error


def test_failure_while_building_the_llm_is_a_setup_failure(monkeypatch):
    def boom(cfg, usage_id):
        raise LLMContextWindowTooSmallError(8192, 16384)

    monkeypatch.setattr(llm_check, "build_llm", boom)

    result = llm_check.check_llm(_cfg(model="ollama/llama3"))

    assert not result.ok
    assert result.error_kind == "setup"
    assert "LLMContextWindowTooSmallError" in result.error


# --- certo-admin check-llm --------------------------------------------------


def _run(monkeypatch, argv, cfg=None):
    monkeypatch.setattr(admin_cli, "load_config", lambda: cfg or _cfg())
    with pytest.raises(SystemExit) as exc:
        admin_cli.main(["check-llm", *argv])
    return exc.value.code


def test_cli_success_exits_zero_and_prints_reply(monkeypatch, capsys):
    _patch(monkeypatch, _response("OK"))

    assert _run(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "Checking openai/gpt-4o" in out
    assert "OK — answered" in out and "'OK'" in out
    assert "Tokens: 17 in / 4 out" in out


def test_cli_failure_exits_one_with_hint_and_never_prints_the_key(monkeypatch, capsys):
    _patch(monkeypatch, LLMAuthenticationError(f"bad key {SECRET}"))

    assert _run(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "FAILED (authentication)" in out
    assert "Hint:" in out
    assert SECRET not in out


def test_cli_overrides_model_and_base_url_for_the_check(monkeypatch, capsys):
    seen = {}

    def build(cfg, usage_id):
        seen["cfg"] = cfg
        return FakeLLM(_response("OK"))

    monkeypatch.setattr(llm_check, "build_llm", build)

    assert _run(monkeypatch, ["--model", "anthropic/x", "--base-url", "http://h:1"]) == 0
    assert (seen["cfg"].model, seen["cfg"].base_url) == ("anthropic/x", "http://h:1")
    assert "Checking anthropic/x at http://h:1" in capsys.readouterr().out


def test_cli_zero_cost_is_shown_as_unknown(monkeypatch, capsys):
    _patch(monkeypatch, _response("OK", cost=0.0))

    assert _run(monkeypatch, []) == 0
    assert "unknown (no pricing data)" in capsys.readouterr().out


def _tool_response(*names, prompt=17, completion=4, cost=0.00001):
    """A response whose message carries tool_calls — what check_tool_calling
    reads. `names` are the tool names the model "called"."""
    calls = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(
        message=SimpleNamespace(content=[], tool_calls=calls),
        metrics=SimpleNamespace(
            accumulated_token_usage=SimpleNamespace(
                prompt_tokens=prompt, completion_tokens=completion
            ),
            accumulated_cost=cost,
        ),
    )


def _patch_tool(monkeypatch, response):
    """check_tool_calling goes through make_llm_completion, not directly
    through llm.completion — patch that instead of FakeLLM."""
    fake = FakeLLM(None)  # completion() is never called on this path
    monkeypatch.setattr(llm_check, "build_llm", lambda cfg, usage_id: fake)
    monkeypatch.setattr(llm_check, "make_llm_completion", lambda *a, **k: response)
    return fake


# --- _is_ollama --------------------------------------------------------------


def test_is_ollama_recognises_both_prefixes():
    assert llm_check._is_ollama("ollama/llama3")
    assert llm_check._is_ollama("ollama_chat/qwen3")
    assert not llm_check._is_ollama("openai/gpt-4o")
    assert not llm_check._is_ollama("anthropic/claude-sonnet")
    assert not llm_check._is_ollama("llama3")  # a bare name is not Ollama here


# --- _ollama_details ---------------------------------------------------------


def test_ollama_details_returns_empty_for_cloud_model(monkeypatch):
    """The 'nothing changes for cloud models' guarantee starts here:
    neither probe may even be called for a non-Ollama model."""

    def boom(*a, **k):
        pytest.fail("must not probe cloud models")

    monkeypatch.setattr(context_window, "ollama_version", boom)
    monkeypatch.setattr(context_window, "ollama_context_tokens", boom)
    assert llm_check._ollama_details(_cfg()) == {}


def test_ollama_details_populated_from_server(monkeypatch):
    """Window ABOVE the default context_warn_tokens (32768) → no warning."""
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 65536)
    details = llm_check._ollama_details(_cfg(model="ollama/llama3"))
    assert details["ollama_version"] == "0.5.7"
    assert details["context_tokens"] == 65536
    assert details["context_source"] == "server"
    assert "context_warning" not in details


def test_ollama_details_env_override_wins_for_source(monkeypatch):
    """With CERTO_LLM_CONTEXT_TOKENS set, the server must NOT be asked."""
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(
        context_window,
        "ollama_context_tokens",
        lambda *a, **k: pytest.fail("env override should win"),
    )
    cfg = _cfg(model="ollama/llama3", llm_context_tokens=8192)
    details = llm_check._ollama_details(cfg)
    assert details["context_tokens"] == 8192
    assert details["context_source"] == "CERTO_LLM_CONTEXT_TOKENS"
    # 8192 < default context_warn_tokens (32768): a warning IS expected.
    assert "context_warning" in details


def test_ollama_details_no_warning_at_exactly_the_threshold(monkeypatch):
    """Off-by-one guard: `tokens < warn` must be False at equal."""
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 32768)
    # default context_warn_tokens is DEFAULT_CONTEXT_WARN_TOKENS (32768)
    assert "context_warning" not in llm_check._ollama_details(_cfg(model="ollama/llama3"))


def test_ollama_details_warning_is_disabled_when_threshold_is_zero(monkeypatch):
    """context_warn_tokens=0 disables the warning, mirroring runner's early return."""
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 4096)
    cfg = _cfg(model="ollama/llama3", context_warn_tokens=0)
    assert "context_warning" not in llm_check._ollama_details(cfg)


def test_ollama_details_warning_matches_the_runs_message(monkeypatch):
    """The whole point of the field: certo check's warning must be
    byte-identical to a run's for the same model + config."""
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 8192)
    cfg = _cfg(model="ollama/llama3")  # default context_warn_tokens = 32768
    expected = context_window.small_window_warning(
        cfg.model,
        8192,
        cfg.context_warn_tokens,
        bool(cfg.llm_context_tokens),  # False — no override
        cfg.condense,
    )
    assert llm_check._ollama_details(cfg)["context_warning"] == expected


def test_ollama_details_survive_both_probes_failing(monkeypatch):
    """Ollama down → {}; the request result is still reported."""

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(context_window, "ollama_version", boom)
    monkeypatch.setattr(context_window, "ollama_context_tokens", boom)
    assert llm_check._ollama_details(_cfg(model="ollama/llama3")) == {}


def test_ollama_details_partial_when_only_version_fails(monkeypatch):
    """Version probe fails, window probe answers: keep the window."""

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(context_window, "ollama_version", boom)
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 65536)
    details = llm_check._ollama_details(_cfg(model="ollama/llama3"))
    assert "ollama_version" not in details
    assert details["context_tokens"] == 65536


# --- _extra_details (tokens/second) ------------------------------------------


def test_extra_details_computes_tokens_per_second(monkeypatch):
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 65536)
    details = llm_check._extra_details(
        _cfg(model="ollama/llama3"), _response("OK", completion=20), latency=2.0
    )
    assert details["tokens_per_second"] == pytest.approx(10.0)
    assert details["ollama_version"] == "0.5.7"


def test_extra_details_no_tokens_per_second_when_zero_completion():
    details = llm_check._extra_details(_cfg(), _response("OK", completion=0), latency=2.0)
    assert "tokens_per_second" not in details


def test_extra_details_no_division_by_zero_latency():
    details = llm_check._extra_details(_cfg(), _response("OK", completion=20), latency=0.0)
    assert "tokens_per_second" not in details


# --- check_llm: the new fields land on the result ----------------------------


def test_check_llm_populates_ollama_fields(monkeypatch):
    _patch(monkeypatch, _response("OK", completion=10))
    ticks = iter(range(100, 10_000, 2))
    monkeypatch.setattr(llm_check.time, "monotonic", lambda: float(next(ticks)))
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 65536)
    result = llm_check.check_llm(_cfg(model="ollama/llama3"))
    assert result.ok
    assert result.ollama_version == "0.5.7"
    assert result.context_tokens == 65536
    assert result.context_source == "server"
    assert result.tokens_per_second is not None


def test_check_llm_cloud_model_has_no_ollama_fields(monkeypatch):
    """Cloud model: probes are never touched; tok/s IS still computed."""
    _patch(monkeypatch, _response("OK"))
    ticks = iter(range(100, 10_000, 2))
    monkeypatch.setattr(llm_check.time, "monotonic", lambda: float(next(ticks)))

    def boom(*a, **k):
        pytest.fail("must not probe cloud models")

    monkeypatch.setattr(context_window, "ollama_version", boom)
    monkeypatch.setattr(context_window, "ollama_context_tokens", boom)
    result = llm_check.check_llm(_cfg())
    assert result.ollama_version is None
    assert result.context_tokens is None
    assert result.context_source is None
    assert result.context_warning is None
    # tokens_per_second is NOT Ollama-only — it is still computed:
    assert result.tokens_per_second is not None


# --- check_tool_calling: currently zero coverage in this file ----------------


def test_check_tool_calling_success_and_ollama_fields(monkeypatch):
    _patch_tool(monkeypatch, _tool_response("finish", completion=10))
    ticks = iter(range(100, 10_000, 2))
    monkeypatch.setattr(llm_check.time, "monotonic", lambda: float(next(ticks)))
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 65536)
    result = llm_check.check_tool_calling(_cfg(model="ollama/llama3"))
    assert result.ok and result.reply == "finish"
    assert result.ollama_version == "0.5.7"
    assert result.context_tokens == 65536
    assert result.tokens_per_second is not None


def test_check_tool_calling_no_tool_is_a_failure(monkeypatch):
    _patch_tool(monkeypatch, _tool_response())  # no calls
    result = llm_check.check_tool_calling(_cfg())
    assert not result.ok
    assert result.error_kind == "no_tool_call"


# --- _failure (step 3d): version + window survive the failure path -----------


def test_setup_failure_still_reports_ollama_details(monkeypatch):
    """The <16K window case: SDK rejects at build time, but the user still
    needs to see the server's version and the window that caused it."""

    def boom(cfg, usage_id):
        raise LLMContextWindowTooSmallError(8192, 16384)

    monkeypatch.setattr(llm_check, "build_llm", boom)
    monkeypatch.setattr(context_window, "ollama_version", lambda *a, **k: "0.5.7")
    monkeypatch.setattr(context_window, "ollama_context_tokens", lambda *a, **k: 8192)
    result = llm_check.check_llm(_cfg(model="ollama/llama3"))
    assert not result.ok
    assert result.error_kind == "setup"
    assert result.ollama_version == "0.5.7"
    assert result.context_tokens == 8192
    assert result.tokens_per_second is None  # no response, no tok/s


def test_failure_with_ollama_down_has_no_details(monkeypatch):
    """Probes fail too → the failure path stays clean (no traceback)."""

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(context_window, "ollama_version", boom)
    monkeypatch.setattr(context_window, "ollama_context_tokens", boom)
    _patch(monkeypatch, RuntimeError("unreachable"))
    result = llm_check.check_llm(_cfg(model="ollama/llama3"))
    assert result.ollama_version is None
    assert result.context_tokens is None
    assert result.error_kind == "error"


# --- detail_lines: the cloud-unchanged regression test -----------------------


def test_detail_lines_empty_for_cloud_model():
    """THE regression test. If this fails, certo check prints a '1.2s' line
    for every cloud model — violating 'nothing changes for cloud models'."""
    result = llm_check.LLMCheckResult(
        ok=True,
        model="openai/gpt-4o",
        base_url=None,
        latency_seconds=1.2,
    )
    assert llm_check.detail_lines(result) == []


def test_detail_lines_ollama_success():
    result = llm_check.LLMCheckResult(
        ok=True,
        model="ollama/llama3",
        base_url=None,
        latency_seconds=1.8,
        ollama_version="0.5.7",
        context_tokens=32768,
        context_source="server",
        tokens_per_second=41.2,
    )
    assert llm_check.detail_lines(result) == [
        "Ollama 0.5.7 · context window 32,768 tokens (from server) · 1.8s, 41.2 tok/s"
    ]


def test_detail_lines_env_override_source():
    result = llm_check.LLMCheckResult(
        ok=True,
        model="ollama/llama3",
        base_url=None,
        latency_seconds=1.8,
        ollama_version="0.5.7",
        context_tokens=8192,
        context_source="CERTO_LLM_CONTEXT_TOKENS",
        tokens_per_second=41.2,
    )
    line = llm_check.detail_lines(result)[0]
    assert "(from CERTO_LLM_CONTEXT_TOKENS)" in line
    assert "8,192" in line


def test_detail_lines_warning_on_its_own_line():
    result = llm_check.LLMCheckResult(
        ok=True,
        model="ollama/llama3",
        base_url=None,
        latency_seconds=1.8,
        ollama_version="0.5.7",
        context_tokens=8192,
        context_source="server",
        tokens_per_second=41.2,
        context_warning="Certo: window is small",
    )
    lines = llm_check.detail_lines(result)
    assert len(lines) == 2
    assert "Ollama 0.5.7" in lines[0]
    assert lines[1] == "Certo: window is small"


def test_detail_lines_failure_still_shows_version_and_window():
    """The case the issue exists for: a setup failure whose header is
    still informative."""
    result = llm_check.LLMCheckResult(
        ok=False,
        model="ollama/llama3",
        base_url=None,
        latency_seconds=0.2,
        ollama_version="0.5.7",
        context_tokens=8192,
        context_source="server",
        error_kind="setup",
        error="window too small",
    )
    lines = llm_check.detail_lines(result)
    assert lines
    assert "Ollama 0.5.7" in lines[0]
    assert "8,192" in lines[0]
