# `certo ask` on its question set (0.2.4)

`certo ask` answers questions about Certo from its docs. Its question set,
[`ask-questions-0.2.4.yaml`](ask-questions-0.2.4.yaml), has 30
questions: 24 with an answer in the docs (some asked twice, in other
words), and 6 the docs don't answer. A covered answer is right when it
holds the expected fact and cites one of the expected pages; an uncovered
one is right when it says the docs don't cover it. Graded by
`scripts/ask_eval.py`, run on 2026-11-16 from a checkout of 0.2.4 (its
docs), with `anthropic/claude-haiku-5-5`.

## Result

| Run | Right | Wrong | Made up | No link | Time | Cost |
|---|---|---|---|---|---|---|
| First | 28 / 30 | 2 | 0 | 0 | 2.8 min | $0.0497 |
| After the fix below | 30 / 30 | 0 | 0 | 0 | 2.9 min | $0.0262 |

No answer made something up: each of the 6 uncovered questions got
"The docs don't cover this." in both runs.

## What the first run missed, and the fix

- *"How do I see the full system prompt the agent gets?"*: "not
  covered". The answer is `CERTO_VERBOSE`, in a section titled "Limits
  and verification", which the model didn't pick from its title, and
  `--verbose` is far down the 13,000-character `certo` section, past the
  6,000 characters sent.
- *"Can a second model write tests to check the agent's work?"*: the
  answer didn't name `--independent-tests`.

Two changes followed: a long section is cut around the lines that use
the question's words (its start is kept), not only its start; and a
question with no exact name (no flag, setting or command) also gets the
section sharing the most of its words. Both are in the second run.

## The runs

First run:

Model: anthropic/claude-haiku-5-5 · docs: checkout · 30 questions

| Question | Result | Pages cited | Time |
|---|---|---|---|
| time-budget | right | reference/commands.md, reference/configuration.md | 6s |
| time-budget-p | right | concepts/safety.md, reference/configuration.md | 7s |
| step-limit | right | concepts/safety.md, reference/configuration.md | 6s |
| cost-limit | right | guides/keep-costs-down.md, guides/run-records-and-costs.md | 5s |
| resume | right | guides/resume-a-run.md, troubleshooting.md | 6s |
| resume-p | right | guides/resume-a-run.md | 7s |
| no-progress | right | guides/after-the-verdict.md, reference/verdicts.md, troubleshooting.md | 6s |
| inconclusive-no-tests | right | guides/after-the-verdict.md, reference/verdicts.md, troubleshooting.md | 8s |
| verify-only | right | guides/verify-in-ci.md, reference/commands.md | 5s |
| undo | right | guides/checkpoints.md, guides/review-the-agents-work.md, reference/commands.md | 8s |
| undo-p | right | guides/checkpoints.md, guides/review-the-agents-work.md | 6s |
| checkpoints-need | right | guides/checkpoints.md, reference/commands.md | 5s |
| json | right | reference/json-result.md | 6s |
| verbose | not covered | - | 5s |
| update-check | right | reference/configuration.md | 4s |
| projects-dir | right | guides/work-on-an-existing-project.md, reference/commands.md, reference/configuration.md | 6s |
| python-version | right | getting-started.md, troubleshooting.md | 5s |
| milestones-format | right | guides/run-in-milestones.md | 7s |
| make-milestones | right | guides/run-in-milestones.md | 6s |
| escalate | right | concepts/auto-model-or-escalation.md, guides/escalate-between-models.md | 6s |
| auto-model | right | concepts/auto-model-or-escalation.md, guides/pick-models-automatically.md, reference/commands.md | 8s |
| independent-tests | wrong fact | guides/independent-tests.md | 6s |
| report | right | guides/run-records-and-costs.md, reference/commands.md | 5s |
| keys-where | right | concepts/safety.md, concepts/where-model-settings-come-from.md, guides/openai-claude-gemini.md | 8s |
| kubernetes | right | - | 5s |
| fortran | right | - | 4s |
| gpu | right | - | 3s |
| vscode-theme | right | - | 3s |
| sla | right | - | 3s |
| price | right | - | 3s |

Total: not covered 1, right 28, wrong fact 1 · 2.8 minutes · $0.0497

After the fix:

Model: anthropic/claude-haiku-5-5 · docs: checkout · 30 questions

| Question | Result | Pages cited | Time |
|---|---|---|---|
| time-budget | right | reference/commands.md, reference/configuration.md | 6s |
| time-budget-p | right | concepts/safety.md, reference/configuration.md | 8s |
| step-limit | right | concepts/safety.md, reference/configuration.md | 5s |
| cost-limit | right | guides/keep-costs-down.md, guides/run-records-and-costs.md, reference/configuration.md | 5s |
| resume | right | guides/resume-a-run.md | 6s |
| resume-p | right | guides/resume-a-run.md | 8s |
| no-progress | right | concepts/how-verification-works.md, guides/after-the-verdict.md, reference/verdicts.md | 6s |
| inconclusive-no-tests | right | guides/after-the-verdict.md, reference/verdicts.md | 8s |
| verify-only | right | guides/verify-in-ci.md, reference/commands.md | 6s |
| undo | right | guides/checkpoints.md, reference/commands.md | 6s |
| undo-p | right | guides/checkpoints.md, guides/review-the-agents-work.md, reference/commands.md | 6s |
| checkpoints-need | right | guides/checkpoints.md, reference/commands.md | 5s |
| json | right | reference/json-result.md | 6s |
| verbose | right | reference/commands.md | 6s |
| update-check | right | reference/configuration.md | 5s |
| projects-dir | right | guides/work-on-an-existing-project.md, reference/commands.md, reference/configuration.md | 5s |
| python-version | right | getting-started.md, troubleshooting.md | 5s |
| milestones-format | right | guides/run-in-milestones.md | 7s |
| make-milestones | right | guides/run-in-milestones.md, reference/commands.md | 5s |
| escalate | right | concepts/auto-model-or-escalation.md, guides/escalate-between-models.md | 6s |
| auto-model | right | concepts/auto-model-or-escalation.md, guides/pick-models-automatically.md, reference/models-yaml.md | 7s |
| independent-tests | right | guides/independent-tests.md | 7s |
| report | right | guides/run-records-and-costs.md, reference/commands.md | 5s |
| keys-where | right | concepts/safety.md, concepts/where-model-settings-come-from.md, guides/openai-claude-gemini.md, reference/configuration.md | 8s |
| kubernetes | right | - | 5s |
| fortran | right | - | 7s |
| gpu | right | - | 5s |
| vscode-theme | right | - | 4s |
| sla | right | - | 3s |
| price | right | - | 2s |

Total: right 30 · 2.9 minutes · $0.0262

## Not yet

A local model (`qwen3.8`, at night) on the same set: see TODO.md.
