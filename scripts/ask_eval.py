"""Grade `certo ask` on its question set (docs/benchmark/ask-questions-*.yaml).

    uv run python scripts/ask_eval.py docs/benchmark/ask-questions-0.2.4.yaml

Uses the model `certo ask` would (CERTO_ASK_MODEL, else the configured
model; CERTO_LLM_MODEL in the environment overrides the settings files)
and this checkout's docs. For each question it prints whether the answer
was right, and why not:

- covered question: right when the answer contains one of `expect` and
  cites one of `pages`; "no link" when it cites nothing; "not covered"
  when it said the docs don't cover it; "wrong page" or "wrong fact";
- uncovered question: right when the answer says so; "made up" when it
  answered anyway.

Prints a Markdown table to paste into a record page, then the totals.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def grade(q: dict, answer) -> str:
    """ "right", or what went wrong."""
    if q.get("covered", True) is False:
        return "made up" if answer.covered else "right"
    if not answer.covered:
        return "not covered"
    if answer.uncited:
        return "no link"
    text = answer.text.casefold()
    if not any(e.casefold() in text for e in q["expect"]):
        return "wrong fact"
    if not any(s.page in q["pages"] for s in answer.cited):
        return "wrong page"
    return "right"


def main(argv: list[str]) -> int:
    from certo import __version__
    from certo.ask_cmd import _ask_config, ask
    from certo.docs_index import split_sections, table_of_contents
    from certo.docs_source import find_docs, user_pages
    from certo.llm import complete_once

    if len(argv) != 1:
        print("usage: ask_eval.py QUESTIONS.yaml", file=sys.stderr)
        return 2
    questions = yaml.safe_load(Path(argv[0]).read_text(encoding="utf-8"))["questions"]
    cfg = _ask_config()
    docs = find_docs(__version__)
    sections = split_sections(user_pages(docs.folder))
    toc = table_of_contents(sections)

    def complete(prompt: str) -> tuple[str, float]:
        return complete_once(cfg, prompt, usage_id="ask-eval")

    rows, totals, cost, seconds = [], {}, 0.0, 0.0
    for q in questions:
        answer = ask(q["question"], sections, complete, toc=toc)
        verdict = grade(q, answer)
        totals[verdict] = totals.get(verdict, 0) + 1
        cost += answer.cost
        seconds += answer.seconds
        cited = ", ".join(sorted({s.page for s in answer.cited})) or "-"
        rows.append(f"| {q['id']} | {verdict} | {cited} | {answer.seconds:.0f}s |")
        print(f"{q['id']}: {verdict}", file=sys.stderr, flush=True)
    print(f"Model: {cfg.model} · docs: {docs.where} · {len(questions)} questions\n")
    print("| Question | Result | Pages cited | Time |\n|---|---|---|---|")
    print("\n".join(rows))
    summary = ", ".join(f"{k} {v}" for k, v in sorted(totals.items()))
    print(f"\nTotal: {summary} · {seconds / 60:.1f} minutes · ${cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main(sys.argv[1:]))
