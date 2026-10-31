# Build an app in several tasks

This guide walks through building a small app with Certo one piece at a
time: how to cut the app into milestones, what to write in each one,
how the run goes, and what to do when a milestone fails. The example is
a real run: a spreadsheet engine, built in 5 milestones by
`claude-haiku-5-5`, every milestone `verified`.

For the reference of the feature itself (the file format, the flags,
`--resume`), see [Run a task in milestones](run-in-milestones.md).

## Why build in pieces

One big task asks the agent to hold the whole app in mind at once, and
it asks Certo to judge everything only at the end. Split into
milestones:

- each piece is checked before the next starts, so a mistake is caught
  where it was made, not three features later;
- an earlier piece that stops working is caught too: every milestone
  re-runs the checks of the milestones before it;
- when a piece fails, the work before it is kept, and
  `certo --resume` continues from that piece;
- each piece starts in a fresh conversation, so a long build doesn't
  fill the model's context window.

The price is time and money: each milestone starts again, reads the
project and plans. In the example below, building in milestones took
about twice as long and cost about 5 times as much as the same task in
one go on the same model, which also passed every hidden test.
Milestones pay off when the task is too big for the model in one go, or
when you want each step checked.

## Cut the app into milestones

Good milestones build on each other, and each one ends with something
that can be tested on its own. For the spreadsheet engine:

| Milestone | What it adds | Why here |
|---|---|---|
| 1. Numbers, text and arithmetic | the `Sheet` class, cell names, numbers, formulas like `=1+2*3` | everything else uses it |
| 2. References | `=A1+B2*2`, values that follow changes | needs formulas |
| 3. Ranges and functions | `A1:B3`, `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT` | needs references |
| 4. Errors | `#DIV/0!`, `#REF!`, `#CYCLE!` and the others | touches everything before |
| 5. Files and the command line | CSV save and load, `python sheet.py` | the outside of the app |

Some rules that helped:

- **Put what every milestone needs before the first heading.** The
  class, its methods and the cell-name rule are written once, at the
  top; every milestone gets them.
- **Say exactly what "done" means in each milestone,** with examples:
  "`=8/2/2` is `2`", "`B3:A1` is the same range". The agent writes its
  tests from them, and Certo runs those tests.
- **Keep each milestone the size of one ordinary task.** If you can't
  say how to test it, it's too big or too vague.
- **Leave the outside of the app (files, command line) for last.** The
  core is easier to test without it.

The whole task file is
[app-tasks/spreadsheet/task.md](https://github.com/alessioricco/certo/blob/main/app-tasks/spreadsheet/task.md).

## Add acceptance checks where they help

A milestone may hold an ` ```acceptance ` block, checked by Certo
whatever the agent's own tests say. Certo takes it out of the text the
agent gets. The spreadsheet task uses three small ones:

````markdown
## Milestone 4: errors
...
```acceptance
[{"kind": "file_contains", "path": "sheet.py", "contains": "#CYCLE!"}]
```
````

Use them for facts the agent's tests could miss: a file that must
exist, a name that must appear. See [Acceptance checks](acceptance-checks.md).

## Run it

Keep the task file outside the project folder, so the agent can't read
the acceptance checks:

```bash
certo --milestones task.md --project sheet
```

Certo prints each milestone as it starts and ends. The real run:

```text
Milestones: 5, each verified before the next starts
Milestone 1 of 5: numbers, text and arithmetic
Milestone 1 of 5: verified
Milestone 2 of 5: references
Milestone 2 of 5: verified
Milestone 3 of 5: ranges and functions
Milestone 3 of 5: verified
Milestone 4 of 5: errors
Milestone 4 of 5: verified
Milestone 5 of 5: files and the command line
Milestone 5 of 5: verified
Milestones:
  1. numbers, text and arithmetic: verified
  2. references: verified
  3. ranges and functions: verified
  4. errors: verified
  5. files and the command line: verified
Verification: verified
  Total running time: 14m 46s
  Total tokens: 4,939,374 (input 4,748,494, of which cached 4,414,812; output 190,880)
  Total cost: $0.3237
```

Each milestone after the first also got what the one before left: the
project's files with their sizes, and the agent's own summary when it
finished, so it didn't start by exploring the folder.

## What came out

Per milestone, from the project's `.certo/RUNS.md`:

| Milestone | Time | Cost |
|---|---|---|
| 1. Numbers, text and arithmetic | 1m 47s | $0.021 |
| 2. References | 1m 34s | $0.020 |
| 3. Ranges and functions | 3m 27s | $0.036 |
| 4. Errors | 5m 42s | $0.219 |
| 5. Files and the command line | 2m 16s | $0.028 |

The errors milestone cost the most: errors reach into the code of
every milestone before it.

The result was a 418-line `sheet.py` and 98 tests of the agent's own,
in 5 test files. Certo's benchmark keeps 111 hidden tests for this task,
which the agent never saw; the project passed all 111.

The same model given the whole task at once, in a
[benchmark run](../benchmark/milestones-0.1.27.md), also passed all 111
hidden tests, in 6m 40s for $0.06. On a task this size, Haiku doesn't
need milestones; they made each step checked, at a price.

## When a milestone fails

Certo stops at the first milestone that isn't `verified`, and keeps
the earlier work:

```text
Milestones:
  1. storage: retry_exhausted
  2. due dates: not started
```

Then you can:

- **Continue it:** `certo --resume` picks up that milestone's
  conversation, then runs the rest. Add a hint as the task text:
  `certo --resume "keep dates as ISO strings"`.
- **Give it more time:** a milestone that ran out of time
  (`budget_exhausted`) often only needs a larger
  `CERTO_MAX_TASK_SECONDS`. The limit applies to each milestone.
- **Hand it to a stronger model:** `certo --resume --escalate` starts
  the milestone again on the first rung of a ladder, told how the last
  try ended. See [Escalate between models](escalate-between-models.md).
- **Go back:** each milestone starts with a checkpoint named
  `before milestone N`; `certo rollback` returns to it. See
  [Go back to an earlier point](checkpoints.md).
- **Change the plan:** an edited task file can't be resumed. Start
  again with `certo --milestones`.

## On a local model

On `qwen3.8:27b` with Ollama, this task has not ended `verified` yet.
With a 65,536-token window and the handover between milestones, 40
minutes per milestone got all three runs through milestones 1 and 2,
and 60 minutes got all three through milestones 1 to 3; none got
through milestone 4. Details in
[the local benchmark](../benchmark/milestones-60min-0.1.27.md). If you
build on a local model:

- give it a large context window (`CERTO_LLM_CONTEXT_TOKENS`); at
  32,768 tokens, `qwen3.8:27b` gave only empty replies on this task in
  one go;
- give each milestone plenty of time: a slow model spends many minutes
  thinking at the start of each one;
- keep milestones small.

See [Ollama and local models](ollama-and-local-models.md).

## Related

- [Run a task in milestones](run-in-milestones.md): the reference for
  the feature
- [Write a task Certo can check](write-a-good-task.md)
- [Acceptance checks](acceptance-checks.md)
- [Resume an interrupted run](resume-a-run.md)
