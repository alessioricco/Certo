"""Certo's docs split at their headings, for `certo ask`: the table of
contents a model picks sections from, and a keyword score that finds
exact names (a flag, a `CERTO_*` setting, a command, a verdict) the
model might miss. No embeddings (DECISIONS.md, "certo ask", 2026-11-14):
the corpus is small and its names are exact. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```+|~~~+)")
# Exact names in a question: --flags, CERTO_ settings, `certo <command>`,
# snake_case words (verdicts such as no_progress) and `code` spans.
_NAMES = re.compile(
    r"--[a-z][\w-]+|\bCERTO_[A-Z_]+\b|\bcerto(?:-server|-admin)?(?: [a-z][\w-]+){1,2}"
    r"|\b[a-z]+_[a-z_]+\b|`([^`]+)`"
)
# A section is cut to this many characters for the answer.
MAX_SECTION_CHARS = 6000


@dataclass(frozen=True)
class Section:
    id: str  # "S12"
    page: str  # path under docs/, e.g. "guides/resume-a-run.md"
    level: int  # 1 for the page title
    title: str
    anchor: str  # GitHub's anchor for the heading
    text: str  # the heading line and what follows, up to the next heading

    @property
    def short_text(self) -> str:
        if len(self.text) <= MAX_SECTION_CHARS:
            return self.text
        return self.text[:MAX_SECTION_CHARS].rstrip() + "\n[…cut]"


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped,
    spaces as hyphens (as tests/test_docs.py checks links)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def split_sections(pages: Iterable[tuple[str, str]]) -> list[Section]:
    """Every page's sections, in order, numbered S1, S2, ... A heading in
    a code block isn't one."""
    sections: list[Section] = []
    for page, text in pages:
        seen: dict[str, int] = {}
        current: tuple[int, str, str] | None = None
        lines: list[str] = []
        fence = None

        def close() -> None:
            if current is None:
                return
            level, title, anchor = current
            body = "\n".join(lines).strip()
            sections.append(Section(f"S{len(sections) + 1}", page, level, title, anchor, body))

        for line in text.splitlines():
            match = _FENCE.match(line)
            if match:
                marker = match.group(1)
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence):
                    fence = None
            heading = _HEADING.match(line) if fence is None and not match else None
            if heading:
                close()
                title = heading.group(2).strip()
                base = slug(title)
                n = seen.get(base, 0)
                seen[base] = n + 1
                current = (len(heading.group(1)), title, base if n == 0 else f"{base}-{n}")
                lines = [line]
            elif current is not None:
                lines.append(line)
        close()
    return sections


def table_of_contents(sections: Sequence[Section], max_level: int = 3) -> str:
    """One line per page (its title), then its sections, indented, each
    with its id: what the first model call picks from."""
    out: list[str] = []
    page = None
    for s in sections:
        if s.page != page:
            page = s.page
            if s.level == 1:
                out.append(f"{s.page}: {s.title} ({s.id})")
                continue
            out.append(f"{s.page}:")
        if s.level <= max_level:
            out.append(f"  {s.id} {s.title}")
    return "\n".join(out)


def names_in(question: str) -> list[str]:
    """The exact names a question uses (see `_NAMES`), in order, once each."""
    found: list[str] = []
    for match in _NAMES.finditer(question):
        name = (match.group(1) or match.group(0)).strip()
        if len(name) > 2 and name not in found:
            found.append(name)
    return found


def keyword_hits(question: str, sections: Sequence[Section], limit: int = 2) -> list[Section]:
    """The sections that name the question's exact names most often, a
    reference page first on a tie; none when the question has no name."""
    names = names_in(question)
    if not names:
        return []
    scored = []
    for s in sections:
        score = sum(s.text.count(name) for name in names)
        if score:
            scored.append((score, s.page.startswith("reference/"), -int(s.id[1:]), s))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [s for *_, s in scored[:limit]]


# Words too common to say what a question is about.
_STOP = frozenset(
    "about after again also anything before being between certo could does doing every "
    "from have into just like make many more much need only other over same should some "
    "such than that their them then there these they thing this those through what when "
    "where which while will with without would your".split()
)


def words_in(question: str) -> set[str]:
    """The question's content words: 4 letters or more, not common ones."""
    return {w for w in re.findall(r"[a-z][a-z-]{3,}", question.lower()) if w not in _STOP}


def _line_score(line: str, names: Sequence[str], words: set[str]) -> int:
    lower = line.lower()
    return 3 * sum(name in line for name in names) + sum(w in lower for w in words)


def excerpt(section: Section, question: str, limit: int = MAX_SECTION_CHARS) -> str:
    """The section's text for answering `question`: all of it when short;
    else its start and the lines (a table row, a paragraph line) that use
    the question's names or words most, in their order, within `limit`."""
    if len(section.text) <= limit:
        return section.text
    lines = section.text.splitlines()
    names, words = names_in(question), words_in(question)
    head = 0
    size = 0
    while head < len(lines) and size + len(lines[head]) < limit // 4:
        size += len(lines[head]) + 1
        head += 1
    ranked = sorted(
        range(head, len(lines)), key=lambda i: _line_score(lines[i], names, words), reverse=True
    )
    keep = set(range(head))
    for i in ranked:
        if _line_score(lines[i], names, words) == 0 or size + len(lines[i]) + 1 > limit:
            continue
        keep.add(i)
        size += len(lines[i]) + 1
    out: list[str] = []
    for i, line in enumerate(lines):
        if i in keep:
            out.append(line)
        elif out and out[-1] != "[…]":
            out.append("[…]")
    return "\n".join(out)


def word_hits(question: str, sections: Sequence[Section], limit: int = 1) -> list[Section]:
    """For a question with no exact name: the sections sharing the most of
    its content words (at least 2), a reference page first on a tie."""
    words = words_in(question)
    if names_in(question) or len(words) < 2:
        return []
    scored = []
    for s in sections:
        lower = s.text.lower()
        score = sum(w in lower for w in words)
        if score >= 2:
            scored.append((score, s.page.startswith("reference/"), -int(s.id[1:]), s))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [s for *_, s in scored[:limit]]
