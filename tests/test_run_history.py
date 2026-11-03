"""`.certo/RUNS.md`: rendering and appending, on a temp folder. No LLM."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from certo import __version__
from certo.run_history import (
    RunEntry,
    append_run,
    note_models_in_readme,
    render_entry,
    runs_path,
)
from certo.run_summary import ModelUsage, RunSummary

_WHEN = datetime(2026, 10, 19, 8, 5, tzinfo=UTC)


def test_an_entry_names_the_date_verdict_task_version_model_and_cost():
    summary = RunSummary(
        duration_seconds=243,
        models=(ModelUsage(model="openai/gpt-5.6-luna", prompt_tokens=1000, cost=0.0593),),
    )
    text = render_entry(
        RunEntry(
            task="Build Asteroids\nmore lines",
            ended="verified",
            started_at=_WHEN,
            models=["openai/gpt-5.6-luna"],
            summary=summary,
        )
    )

    assert text.startswith("## 2026-10-19 08:05 UTC · verified\n")
    assert "- Task: Build Asteroids\n" in text
    assert f"- Certo: {__version__}\n" in text
    assert "- Model: openai/gpt-5.6-luna\n" in text
    assert "- Time: 4m 03s · Tokens: 1,000 · Cost: $0.0593" in text


def test_an_escalation_entry_lists_every_rung():
    text = render_entry(
        RunEntry(
            task="t",
            ended="verified",
            started_at=_WHEN,
            models=["1. local (ollama/qwen3.8:27b): unchanged", "2. haiku (anthropic/h): verified"],
            note="escalation, final result from rung 2",
            resumed=True,
        )
    )

    assert "- Task: t (resumed)" in text
    assert "- Models: escalation, final result from rung 2\n" in text
    assert "  - 1. local (ollama/qwen3.8:27b): unchanged\n" in text


def test_entries_accumulate_and_the_folder_ignores_itself(tmp_path):
    for verdict in ("retry_exhausted", "verified"):
        append_run(str(tmp_path), RunEntry(task="t", ended=verdict, started_at=_WHEN, models=["m"]))

    text = Path(runs_path(str(tmp_path))).read_text(encoding="utf-8")
    assert text.startswith("# Certo runs in this folder")
    assert text.count("# Certo runs in this folder") == 1
    assert text.index("· retry_exhausted") < text.index("· verified")
    assert (tmp_path / ".certo" / ".gitignore").read_text().strip().endswith("*")


def test_the_readme_note_is_added_once_and_grows_with_new_models(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Wordle\n\nRun it with `python wordle.py`.\n")

    assert note_models_in_readme(str(tmp_path), ["ollama/qwen3.8:27b"])
    assert note_models_in_readme(
        str(tmp_path), ["anthropic/claude-haiku-5-5", "ollama/qwen3.8:27b"]
    )
    assert not note_models_in_readme(str(tmp_path), ["ollama/qwen3.8:27b"])

    text = readme.read_text()
    assert text == (
        "# Wordle\n\nRun it with `python wordle.py`.\n\n"
        "<!-- certo:models -->\n"
        "*Generated with [Certo](https://github.com/alessioricco/certo), using "
        "`ollama/qwen3.8:27b`, `anthropic/claude-haiku-5-5`.*\n"
        "<!-- /certo:models -->\n"
    )


def test_text_after_the_note_is_kept(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "# App\n\n<!-- certo:models -->\n*old*\n<!-- /certo:models -->\n\n## License\n\nMIT\n"
    )

    note_models_in_readme(str(tmp_path), ["openai/gpt-5.6-luna"])

    text = readme.read_text()
    assert text.count("<!-- certo:models -->") == 1
    assert "`openai/gpt-5.6-luna`" in text
    assert text.endswith("<!-- /certo:models -->\n\n## License\n\nMIT\n")


def test_no_readme_or_no_model_means_no_note(tmp_path):
    assert not note_models_in_readme(str(tmp_path), ["m"])
    (tmp_path / "README.md").write_text("# App\n")
    assert not note_models_in_readme(str(tmp_path), [])
    assert (tmp_path / "README.md").read_text() == "# App\n"


def test_an_entry_links_its_report():
    text = render_entry(
        RunEntry(
            task="t",
            ended="verified",
            started_at=_WHEN,
            models=["m"],
            report="reports/2026-11-03T16-19-05Z.md",
        )
    )

    assert "- Report: [reports/2026-11-03T16-19-05Z.md](reports/2026-11-03T16-19-05Z.md)" in text
