"""The docs/ pages must keep up with the code.

A safety net, not a documentation generator: each test collects names from
the code (the settings config.py reads, the argparse flags, the verdicts)
and fails when the matching reference page doesn't mention one. The last
tests fail on a relative Markdown link whose file or heading is missing.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from certo import (
    admin_cli,
    ask_cmd,
    bench,
    checkpoints_cmd,
    cli,
    config,
    init_cmd,
    init_models,
    models_cmd,
    report_cmd,
    server,
    skills_cmd,
)
from certo.verification import CHECK_STATUSES
from certo.runner import VERIFICATION_STATES

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"

# docs/ isn't in the sdist, whose tests/ folder still ships.
pytestmark = pytest.mark.skipif(not _DOCS.is_dir(), reason="no docs/ folder here")


def _page(name: str) -> str:
    return (_DOCS / name).read_text(encoding="utf-8")


# --- Settings ----------------------------------------------------------------


class _RecordingEnv(dict):
    """An environment that remembers every variable name looked up in it."""

    def __init__(self, **values: str) -> None:
        super().__init__(values)
        self.looked_up: set[str] = set()

    def get(self, key, default=None):
        self.looked_up.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.looked_up.add(key)
        return super().__getitem__(key)


def _settings_read_by_config() -> list[str]:
    env = _RecordingEnv(CERTO_LLM_MODEL="openai/some-model", CERTO_LLM_API_KEY="x")
    config.load_config(env)
    return sorted(name for name in env.looked_up if name.startswith("CERTO_"))


def test_every_setting_is_in_the_configuration_reference():
    names = _settings_read_by_config()
    assert len(names) > 30, "too few settings found; the recording is probably broken"
    page = _page("reference/configuration.md")
    missing = [name for name in names if f"`{name}`" not in page]
    assert missing == [], f"docs/reference/configuration.md doesn't mention: {missing}"


# --- Commands and flags ------------------------------------------------------


class _StopParsing(Exception):
    pass


def _server_parser() -> argparse.ArgumentParser:
    """certo-server builds its parser inside main(); catch it at parse_args."""
    captured = {}

    def capture(self, args=None, namespace=None):
        captured["parser"] = self
        raise _StopParsing

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(argparse.ArgumentParser, "parse_args", capture)
        with pytest.raises(_StopParsing):
            server.main([])
    return captured["parser"]


def _with_subparsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _with_subparsers(sub)


def _all_parsers() -> list[argparse.ArgumentParser]:
    roots = [
        cli._build_parser(),
        cli._build_verify_parser(),
        init_cmd.build_init_parser(),
        init_cmd.build_check_parser(),
        init_models.build_parser(),
        models_cmd.build_parser(),
        skills_cmd.build_parser(),
        bench.build_bench_parser(),
        checkpoints_cmd.build_checkpoints_parser(),
        checkpoints_cmd.build_rollback_parser(),
        report_cmd.build_report_parser(),
        ask_cmd.build_ask_parser(),
        admin_cli.build_parser(),
        _server_parser(),
    ]
    return [parser for root in roots for parser in _with_subparsers(root)]


def _sections(markdown: str) -> dict[str, str]:
    """Heading text (backticks removed) -> the text up to the next heading."""
    sections: dict[str, str] = {}
    current = None
    for line in markdown.splitlines():
        heading = re.match(r"#+\s+(.*)", line)
        if heading:
            current = heading.group(1).replace("`", "").strip()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def test_every_command_and_flag_is_in_the_commands_reference():
    sections = _sections(_page("reference/commands.md"))
    parsers = _all_parsers()
    assert len(parsers) > 15, "too few parsers found; the discovery is probably broken"
    problems = []
    for parser in parsers:
        if parser.prog not in sections:
            problems.append(f"no section headed `{parser.prog}`")
            continue
        for action in parser._actions:
            for flag in action.option_strings:
                if flag in ("-h", "--help"):
                    continue
                if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", sections[parser.prog]):
                    problems.append(f"`{parser.prog}` section doesn't mention {flag}")
    assert problems == [], "docs/reference/commands.md: " + "; ".join(problems)


# --- Verdicts ----------------------------------------------------------------


def _verdict_rows() -> dict[str, list[str]]:
    """The '## All verdicts' table: verdict -> its cells."""
    section = _sections(_page("reference/verdicts.md"))["All verdicts"]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and re.fullmatch(r"`[a-z_]+`", cells[0]):
            rows[cells[0].strip("`")] = cells
    return rows


def test_every_verdict_is_in_the_verdicts_reference_with_its_exit_code():
    rows = _verdict_rows()
    missing = [state for state in VERIFICATION_STATES if state not in rows]
    assert missing == [], f"docs/reference/verdicts.md has no row for: {missing}"
    wrong_exit = []
    for state in VERIFICATION_STATES:
        expected = "1" if state in cli._FAILING_STATES else "0"
        if not rows[state][-1].startswith(expected):
            wrong_exit.append(f"{state} (expected exit {expected}, page says {rows[state][-1]!r})")
    assert wrong_exit == [], f"docs/reference/verdicts.md: wrong exit code for {wrong_exit}"


def test_every_check_status_is_in_the_verdicts_reference():
    page = _page("reference/verdicts.md")
    missing = [status for status in CHECK_STATUSES if f"`{status}`" not in page]
    assert missing == [], f"docs/reference/verdicts.md doesn't mention: {missing}"


# --- Links -------------------------------------------------------------------

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)


def _without_code(markdown: str) -> str:
    return re.sub(r"`[^`\n]*`", "", _FENCE.sub("", markdown))


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped,
    spaces as hyphens."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    for line in _FENCE.sub("", path.read_text(encoding="utf-8")).splitlines():
        heading = re.match(r"#+\s+(.*)", line)
        if heading:
            slug = _slug(heading.group(1))
            n = 0
            while (slug if n == 0 else f"{slug}-{n}") in anchors:
                n += 1
            anchors.add(slug if n == 0 else f"{slug}-{n}")
    return anchors


def _broken_links(path: Path, targets: list[str]) -> list[str]:
    broken = []
    for target in targets:
        file_part, _, anchor = target.partition("#")
        resolved = (path.parent / file_part).resolve() if file_part else path
        where = f"{path.relative_to(_ROOT)} -> {target}"
        if not resolved.exists():
            broken.append(f"{where} (no such file)")
        elif anchor and resolved.suffix == ".md" and anchor not in _anchors(resolved):
            broken.append(f"{where} (no such heading)")
    return broken


def _relative_targets(markdown: str) -> list[str]:
    return [
        target
        for target in _LINK.findall(_without_code(markdown))
        if not target.startswith(("http://", "https://", "mailto:"))
    ]


def test_relative_links_in_docs_point_at_existing_files_and_headings():
    pages = sorted(_DOCS.rglob("*.md"))
    assert len(pages) > 20, "too few pages found"
    broken = []
    for page in pages:
        broken += _broken_links(page, _relative_targets(page.read_text(encoding="utf-8")))
    assert broken == [], "broken links:\n" + "\n".join(broken)


_BLOB = "https://github.com/alessioricco/certo/blob/main/"


def test_readme_and_manual_links_to_this_repo_point_at_existing_files_and_headings():
    """README.md (also the PyPI page) uses absolute GitHub links; MANUAL.md
    maps old sections to the new pages with relative ones."""
    broken = []
    for name in ("README.md", "MANUAL.md"):
        path = _ROOT / name
        text = path.read_text(encoding="utf-8")
        targets = _relative_targets(text) + [
            t.removeprefix(_BLOB) for t in _LINK.findall(_without_code(text)) if t.startswith(_BLOB)
        ]
        broken += _broken_links(path, targets)
    assert broken == [], "broken links:\n" + "\n".join(broken)
