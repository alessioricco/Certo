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
"""

from __future__ import annotations

import argparse
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

PICK_PROMPT = """You help answer a question about Certo, a command-line tool \
that runs a coding agent and checks its work. Below are the sections of \
Certo's documentation, by page, each with an id such as S12.

Name the sections most likely to answer the question: at most {most}, \
best first, as their ids on one line, such as: S12 S40 S7
If none could, answer: NONE

Question: {question}

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

Question: {question}

Sections:
{sections}
"""

_IDS = re.compile(r"\bS(\d+)\b")
_CITE = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")

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


def ask(
    question: str, sections: Sequence[Section], complete: Complete, toc: str | None = None
) -> Answer:
    """Answer `question` from `sections` with two calls of `complete`."""
    started = time.monotonic()
    toc = toc if toc is not None else table_of_contents(sections)
    reply, cost = complete(PICK_PROMPT.format(most=MAX_PICKED, question=question, toc=toc))
    used = pick_sections(question, sections, reply)
    if not used:
        return Answer(question, "", False, [], seconds=time.monotonic() - started, cost=cost)
    text, more = complete(
        ANSWER_PROMPT.format(
            not_covered=NOT_COVERED, question=question, sections=_sections_text(used, question)
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


def render(answer: Answer, docs: Docs) -> list[str]:
    """What the terminal shows: the answer with its sources, or that the
    docs don't cover it with the closest pages."""
    if not answer.covered:
        lines = ["The docs don't cover this."]
        if answer.used:
            lines += ["", "The closest pages:"]
            seen: list[str] = []
            for s in answer.used:
                if s.page not in seen:
                    seen.append(s.page)
                    lines.append(f"  {docs.link(s.page)}")
        return lines
    numbers = {s.id: n for n, s in enumerate(answer.cited, start=1)}

    def renumber(match: re.Match) -> str:
        ids = re.split(r"\s*,\s*", match.group(1))
        shown = [str(numbers[i]) for i in ids if i in numbers]
        return f"[{', '.join(shown)}]" if shown else ""

    lines = [_CITE.sub(renumber, answer.text).rstrip()]
    if answer.cited:
        lines += ["", "Sources:"]
        lines += [
            f"  [{n}] {_heading_path(s)}\n      {docs.link(s.page, s.anchor)}"
            for s, n in ((s, numbers[s.id]) for s in answer.cited)
        ]
    else:
        lines += [
            "",
            "Note: this answer names no section of the docs, so it can't be checked "
            "against them. The pages it was given:",
        ]
        lines += [f"  {docs.link(s.page, s.anchor)}" for s in answer.used]
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
    return parser


def _ask_config():
    """The config to answer with: CERTO_ASK_MODEL's model, else the
    configured one. Raises ConfigError."""
    from .config import load_config
    from .model_selection import config_for_named_model

    cfg = load_config()
    if cfg.ask_model:
        return config_for_named_model(cfg, cfg.ask_model, "CERTO_ASK_MODEL")
    return cfg


def ask_main(argv: list[str], *, complete: Complete | None = None, docs: Docs | None = None) -> int:
    args = build_ask_parser().parse_args(argv)
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
    try:
        answer = ask(question, sections, complete)
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
