"""`certo ask "<question>"`: an answer about Certo from its own docs, with a
link to each section it used (DECISIONS.md, "certo ask", 2026-11-14).

Two model calls. The first gets the question and the docs' table of
contents (headings, ~5K tokens) and names up to 5 sections; the sections
whose text names the question's exact names (a flag, a setting) are added
to them. The second answers from those sections only, citing each one it
uses as `[S12]`, or says the docs don't cover the question. Certo turns
the citations into links and lists the closest pages for an uncovered
question. An answer that cites nothing is shown with a warning: it can't
be checked against the docs.

The model: `CERTO_ASK_MODEL` (a models.yaml name), else the configured
model. Both calls fit a 32K context window. Only the question goes to the
model; GitHub sees only the version when the docs are downloaded.

`--mine` (opt-in) also sends the user's own setup, for questions such as
"why did my run pick Opus?": what `certo check` prints without its model
call, the project's `MODEL_DECISIONS.md` and its last run report, each
cited as `[Y1]`..`[Y3]`, with every key-like value hidden as `certo report`
hides it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import __version__
from .docs_index import (
    Section,
    excerpt,
    keyword_hits,
    split_sections,
    table_of_contents,
    word_hits,
)
from .docs_source import Docs, DocsUnavailable, find_docs, user_pages

NOT_COVERED = "NOT COVERED"
MAX_PICKED = 5
# The sections' text sent with the question, at most (about 10K tokens).
MAX_CONTEXT_CHARS = 40_000
# Each of the user's own files sent with --mine, at most (about 2K tokens):
# three of them keep both calls inside a 32K window.
MAX_MINE_CHARS = 8_000

PICK_PROMPT = """You help answer a question about Certo, a command-line tool \
that runs a coding agent and checks its work. Below are the sections of \
Certo's documentation, by page, each with an id such as S12.

Name the sections most likely to answer the question: at most {most}, \
best first, as their ids on one line, such as: S12 S40 S7
If none could, answer: NONE

Question: {question}
{mine}
Sections:
{toc}
"""

ANSWER_PROMPT = """Answer a question about Certo, a command-line tool that \
runs a coding agent and checks its work, using only the documentation \
sections below.

Rules:
- Use only what the sections say. Don't add anything from elsewhere, and \
don't guess.
- After each sentence that uses a section, cite it by its id in square \
brackets, such as [S12].
- Keep it short: the answer first, then the exact command or setting if \
there is one.
- If the sections don't answer the question, reply only: {not_covered}
{mine_rule}
Question: {question}

Sections:
{sections}
"""

MINE_PICK = """
The user also shares their own setup, below. Pick the documentation \
sections that explain what it shows.

{mine}
"""

MINE_RULE = """- Some sections, with ids such as Y1, are the user's own setup: \
their settings, their models' choices, their last run. Use them for facts \
about the user's setup and the other sections for how Certo works; cite \
both the same way.
"""

_IDS = re.compile(r"\bS(\d+)\b")
_CITE = re.compile(r"\[([SY]\d+(?:\s*,\s*[SY]\d+)*)\]")

# (prompt) -> (reply, cost in US dollars)
Complete = Callable[[str], tuple[str, float]]


@dataclass
class Answer:
    question: str
    text: str  # the model's answer, as it wrote it ("" when not covered)
    covered: bool
    used: list[Section]  # the sections the model got
    cited: list[Section] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    seconds: float = 0.0
    cost: float = 0.0

    @property
    def uncited(self) -> bool:
        """An answer that names no section: it can't be checked."""
        return self.covered and not self.cited


def pick_sections(question: str, sections: Sequence[Section], reply: str) -> list[Section]:
    """The sections the model named (at most MAX_PICKED, in its order),
    then the keyword hits, cut so their text fits MAX_CONTEXT_CHARS."""
    by_id = {s.id: s for s in sections}
    picked: list[Section] = []
    for number in _IDS.findall(reply):
        section = by_id.get(f"S{number}")
        if section is not None and section not in picked and len(picked) < MAX_PICKED:
            picked.append(section)
    for section in keyword_hits(question, sections) + word_hits(question, sections):
        if section not in picked:
            picked.append(section)
    kept, size = [], 0
    for section in picked:
        size += len(excerpt(section, question))
        if size > MAX_CONTEXT_CHARS and kept:
            break
        kept.append(section)
    return kept


def _sections_text(sections: Sequence[Section], question: str) -> str:
    return "\n\n".join(f"[{s.id}] {s.page}\n{excerpt(s, question)}" for s in sections)


def _mine_text(mine: Sequence[Section]) -> str:
    return "\n\n".join(f"[{s.id}] {s.title}\n{s.text}" for s in mine)


def ask(
    question: str,
    sections: Sequence[Section],
    complete: Complete,
    toc: str | None = None,
    mine: Sequence[Section] = (),
) -> Answer:
    """Answer `question` from `sections` with two calls of `complete`;
    `mine` (the user's own files, ids Y1..) goes to both calls."""
    started = time.monotonic()
    toc = toc if toc is not None else table_of_contents(sections)
    mine_pick = MINE_PICK.format(mine=_mine_text(mine)) if mine else ""
    reply, cost = complete(
        PICK_PROMPT.format(most=MAX_PICKED, question=question, mine=mine_pick, toc=toc)
    )
    used = pick_sections(question, sections, reply) + list(mine)
    if not used:
        return Answer(question, "", False, [], seconds=time.monotonic() - started, cost=cost)
    docs_used = [s for s in used if s not in mine]
    text, more = complete(
        ANSWER_PROMPT.format(
            not_covered=NOT_COVERED,
            mine_rule=MINE_RULE if mine else "",
            question=question,
            sections="\n\n".join(
                part for part in (_sections_text(docs_used, question), _mine_text(mine)) if part
            ),
        )
    )
    cost += more
    text = text.strip()
    seconds = time.monotonic() - started
    if not text or text.upper().startswith(NOT_COVERED):
        return Answer(question, "", False, used, seconds=seconds, cost=cost)
    by_id = {s.id: s for s in used}
    cited: list[Section] = []
    unknown: list[str] = []
    for group in _CITE.findall(text):
        for sid in re.split(r"\s*,\s*", group):
            if sid in by_id:
                if by_id[sid] not in cited:
                    cited.append(by_id[sid])
            elif sid not in unknown:
                unknown.append(sid)
    return Answer(question, text, True, used, cited, unknown, seconds, cost)


def _heading_path(section: Section) -> str:
    return f"{section.page} › {section.title.replace('`', '')}"


def _is_mine(section: Section) -> bool:
    return section.id.startswith("Y")


def _source(section: Section, docs: Docs) -> str:
    if _is_mine(section):
        return f"Yours › {section.title}\n      {section.page}"
    return f"{_heading_path(section)}\n      {docs.link(section.page, section.anchor)}"


def render(answer: Answer, docs: Docs) -> list[str]:
    """What the terminal shows: the answer with its sources, or that the
    docs don't cover it with the closest pages."""
    if not answer.covered:
        lines = ["The docs don't cover this."]
        pages: list[str] = []
        for s in answer.used:
            if s.page not in pages and not _is_mine(s):
                pages.append(s.page)
        if pages:
            lines += ["", "The closest pages:", *(f"  {docs.link(page)}" for page in pages)]
        return lines
    numbers = {s.id: n for n, s in enumerate(answer.cited, start=1)}

    def renumber(match: re.Match) -> str:
        ids = re.split(r"\s*,\s*", match.group(1))
        shown = [str(numbers[i]) for i in ids if i in numbers]
        return f"[{', '.join(shown)}]" if shown else ""

    lines = [_CITE.sub(renumber, answer.text).rstrip()]
    if answer.cited:
        lines += ["", "Sources:"]
        lines += [f"  [{numbers[s.id]}] {_source(s, docs)}" for s in answer.cited]
    else:
        lines += [
            "",
            "Note: this answer names no section of the docs, so it can't be checked "
            "against them. The pages it was given:",
        ]
        lines += [
            f"  {s.page if _is_mine(s) else docs.link(s.page, s.anchor)}" for s in answer.used
        ]
    return lines


def build_ask_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certo ask",
        description=(
            "Answer a question about Certo from its own docs (this version's), with a "
            "link to each section used. Uses CERTO_ASK_MODEL, else your configured model."
        ),
    )
    parser.add_argument("question", nargs="+", help="The question, in your own words.")
    parser.add_argument(
        "--mine",
        action="store_true",
        help=(
            "Also send your own setup: what `certo check` prints (without its model "
            "call), the project's MODEL_DECISIONS.md and its last run report, with keys "
            "hidden. For questions such as 'why did my run pick Opus?'."
        ),
    )
    parser.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help=(
            "With --mine: the project under CERTO_PROJECTS_DIR to read, as a run with "
            "--project NAME uses it (default: the current folder)."
        ),
    )
    return parser


def _cut(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_MINE_CHARS:
        return text
    return text[:MAX_MINE_CHARS].rstrip() + "\n[…cut]"


def _check_text(project: str) -> str:
    """What `certo check` prints, without its model call: the settings and
    where they came from, and the model files' report."""
    import io

    from .catalog_report import print_catalog_report
    from .config import load_settings_files
    from .init_cmd import print_setting_sources

    out = io.StringIO()
    print_setting_sources(load_settings_files(), out)

    def no_call(*_args, **_kwargs):  # test_models=False never calls it
        raise RuntimeError("certo ask --mine calls no model to check")

    print_catalog_report(
        out, test_models=False, timeout=0, check=no_call, explain=no_call, project_dir=project
    )
    return out.getvalue()


def gather_mine(project: str, check_text: Callable[[str], str] = _check_text) -> list[Section]:
    """The user's own files for `--mine`, as sections Y1.. (only those
    found), every key-like value hidden. Read here, never written."""
    from .report_cmd import hide_secrets, known_secrets, latest_report_page

    found: list[tuple[str, str, str]] = []  # (title, where, text)
    try:
        found.append(
            ("Your settings and model files (certo check)", "certo check", check_text(project))
        )
    except Exception as exc:  # noqa: BLE001 - a broken setup is part of the answer
        found.append(
            ("Your settings and model files (certo check)", "certo check", f"Error: {exc}")
        )
    decisions = os.path.join(project, "MODEL_DECISIONS.md")
    report = latest_report_page(project)
    for title, path in (
        ("Your project's MODEL_DECISIONS.md", decisions),
        ("Your last run's report", report),
    ):
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    found.append((title, path, f.read()))
            except OSError:
                pass
    secrets = known_secrets(project)
    mine = []
    for n, (title, where, text) in enumerate(found, start=1):
        text, _ = hide_secrets(_cut(text), secrets)
        mine.append(Section(f"Y{n}", where, 0, title, "", text))
    return mine


def _mine_project(name: str | None) -> str:
    """The folder `--mine` reads: `--project NAME`'s, else this one."""
    if not name:
        return os.path.abspath(".")
    from .config import defer_llm_check, load_config, resolve_project_dir

    with defer_llm_check():
        cfg = load_config()
    return resolve_project_dir(cfg.projects_dir, name)


def _ask_config():
    """The config to answer with: CERTO_ASK_MODEL's model, else the
    configured one. Raises ConfigError."""
    from .config import load_config
    from .model_selection import config_for_named_model

    cfg = load_config()
    if cfg.ask_model:
        return config_for_named_model(cfg, cfg.ask_model, "CERTO_ASK_MODEL")
    return cfg


def ask_main(
    argv: list[str],
    *,
    complete: Complete | None = None,
    docs: Docs | None = None,
    mine: Sequence[Section] | None = None,
) -> int:
    parser = build_ask_parser()
    args = parser.parse_args(argv)
    if args.project and not args.mine:
        parser.error("--project needs --mine")
    question = " ".join(args.question).strip()
    from .config import ConfigError

    try:
        docs = docs or find_docs(__version__)
    except DocsUnavailable as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    model = "the given model"
    if complete is None:
        try:
            cfg = _ask_config()
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1
        from .llm import complete_once

        model = cfg.model

        def complete(prompt: str) -> tuple[str, float]:
            return complete_once(cfg, prompt, usage_id="ask")

    sections = split_sections(user_pages(docs.folder))
    if args.mine and mine is None:
        try:
            mine = gather_mine(_mine_project(args.project))
        except (ConfigError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if mine:
        print("Also sending, with keys hidden:")
        for s in mine:
            print(f"  [{s.id}] {s.title}: {s.page}")
        print()
    try:
        answer = ask(question, sections, complete, mine=mine or ())
    except Exception as exc:  # noqa: BLE001 - a model failure is reported, not a traceback
        print(f"Error: {model} couldn't answer: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for line in render(answer, docs):
        print(line)
    cost = f", ${answer.cost:.4f}" if answer.cost else ""
    print(
        f"\n(Answered by {model} from {len(answer.used)} section(s) in {answer.seconds:.0f}s{cost}.)"
    )
    return 0
