# A trusted skill in a run, Certo 0.2.3

Whether a skill from a trusted repository reaches a real run. One live
run, not a benchmark: it shows the skill is added, not that it helps.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased), local execution.
- **Model:** `anthropic/claude-haiku-5-5`, default effort.
- **Machine:** Darwin 25.6.0, arm64, Apple M1.
- **Run:** 2026-11-07.
- **Trusted repository:** `github:OpenHands/extensions`, `path: skills`,
  assessed at commit `210f2c08fbf5` with `certo skills assess --global`:
  73 skills, 52 usable, 15 to review, 6 rejected.
- **Budget:** `CERTO_TRUSTED_SKILLS_TOKENS` at its default, 4000.
- **The task:** [`trusted-skills-greet-cli.task.md`](trusted-skills-greet-cli.task.md),
  a small Python command-line tool with pytest tests, managed with uv,
  run from an empty Certo workspace with no `--project`.

## Results

| Skill added | Verdict | Time | Tokens | Cost |
|---|---|---|---|---|
| `uv` (about 591 tokens) | `verified` | 33.1s | 201,129 | $0.0083 |

Certo printed, before the run:

```text
Project: projects/greet-cli, named after the task. The agent works only in that folder.
Certo: added the trusted skill 'uv' (github:OpenHands/extensions, about 591 tokens): the task says "uv", for python.
```

The agent set the project up with `uv init --bare` and
`uv add --dev pytest`, which wrote `pyproject.toml` and `uv.lock`, and the
checks passed.

## What this doesn't show

The task itself asked for uv, so the agent may have done the same without
the skill. Whether trusted skills make results better needs the benchmark
with and without them (`CERTO_TRUSTED_SKILLS_TOKENS=0`), on a local and a
cloud model: TODO.md, "Trusted skill repositories", step 5.
