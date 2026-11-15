# What to do after each verdict

This guide says what to do next once a run ends, verdict by verdict. It
is for anyone running tasks with `certo`. What each verdict means exactly,
and its exit code, is in [Verdicts](../reference/verdicts.md). Error
messages and their fixes are in [Troubleshooting](../troubleshooting.md).

## Your tools

Six moves cover almost every case:

| Move | Command | When |
|---|---|---|
| Read where it stopped | open `.certo/STATUS.md` in the project | Any failing verdict. It holds the verdict, the failing checks and the end of their output, written by Certo, not by the agent. |
| See the full check output | `certo verify` (or `certo verify PATH`) | Any time. It runs the same checks with no agent and no model, so it costs nothing. |
| Continue with a hint | `certo --resume "..."` | The agent was close, and you can say what it missed. It keeps its earlier conversation. |
| Continue with a stronger model | `certo --resume --model MODEL` | The model is the problem. The new model reads everything the first one did. |
| Start smaller | a new, smaller task in the same folder | The task was too big for one run. |
| Go back | `certo checkpoints`, then `certo rollback N` | A fix attempt or a model made things worse. See [Go back to an earlier point](checkpoints.md). |

Add `--project NAME` to `--resume` and `verify` if the task used it. See
[Resume an interrupted run](resume-a-run.md).

## `verified`

The project's checks passed. That proves what the checks test, and
nothing more.

1. **Look at what changed.** In a git repository, `git diff` and
   `git status`. Make sure the agent changed what you asked, and nothing
   else.
2. **Look at the tests.** Do they test what the task asked for, with the
   right expected results? The agent's tests can share its
   misunderstandings (see
   [Write a task Certo can check](write-a-good-task.md#3-give-the-expected-answers-yourself)).
3. **Try it.** Run the program, open the page, call the API. Certo can
   start a program but can't use it the way a person does.
4. **Commit**, so the next task starts from a known state.

To keep working on the same project, run the next task with the same
folder or `--project`. `certo --resume` with no text does nothing after
`verified`; give it the next instruction, or start a new task.

## `inconclusive`

Nothing proved the work right or wrong. The lines starting with `-` under
the verdict say why. The common cases:

- **No tests.** Ask for tests: `certo --resume "Add pytest tests for the
  scoring rules"`.
- **A tool is missing** (`npm`, `go`, `cargo`, `mvn`, `gradle`). Install
  it and run `certo verify`: no need to run the agent again.
- **An unknown project type**, such as a standalone HTML page. Check it by
  hand, or ask for a `package.json` with a `test` or `build` script.
- **Several projects in one folder.** Run `certo verify` in the one you
  mean.

To set a project up so this doesn't happen, see
[Make your project checkable](make-a-project-checkable.md). In scripts and
CI, use `--require-verification` so `inconclusive` counts
as a failure. Each case in detail:
[Troubleshooting](../troubleshooting.md#inconclusive-the-project-has-no-tests).

## `unchanged`

The checks passed, but the agent changed no file, even after Certo asked
it once. Read the agent's last message: it usually says why.

- **No change was needed** (for example, "check that the tests pass"):
  you're done.
- **A change was needed:** the agent stopped early, misread the task, or
  wrote files somewhere else. Look for files outside the project folder,
  then resume with a precise instruction, such as
  `certo --resume "inventory.py has no OutOfStock class yet. Add it, as the task says."`,
  or with a stronger `--model`.

If this keeps happening on fix tasks, add an
[acceptance check](acceptance-checks.md) for what must exist afterwards.

## `retry_exhausted`

A check kept failing after the fix attempts (2 by default), with a
different failure each time. The agent was trying, but didn't get there.

1. Read the failure: `certo verify`, or the end of it in
   `.certo/STATUS.md`.
2. If you can see the cause, resume with it:
   `certo --resume "The repeated-letter rule is wrong: mark correct letters first, then present ones only while copies remain."`
3. If the model seems out of its depth, resume with a stronger
   `--model`.
4. If the task asked for a lot, split it (see
   [one step per task](write-a-good-task.md#7-one-step-per-task)).

`CERTO_MAX_VERIFY_RETRIES` allows more attempts, but more attempts by the
same model rarely help: a hint or a stronger model usually does.

## `no_progress`

A fix attempt changed nothing: the same check failed with the same
output. Certo stopped early instead of using up the attempts.

Before resuming, ask whether the **test** is wrong rather than the code.
Agents sometimes keep breaking correct code to satisfy a test that expects
the wrong thing. If so, say which one is right:
`certo --resume "test_invalid_move expects a legal move to fail. Fix the test, not the code."`

Otherwise, treat it like `retry_exhausted`: a precise hint, a stronger
model, or a fix by hand followed by `certo verify`.

## `timed_out`

A check ran longer than 300 seconds and was stopped, and it still did
after the fix attempts. Almost always a program or test that waits for
input, or loops forever.

- Certo runs every check with no input. A program that waits for a key
  press, or a test that starts a server and never stops it, hangs here.
- Resume with: `certo --resume "The tests hang. Make the program exit when
  input ends, and stop any server the tests start."`
- A test suite that really needs more than 5 minutes can't pass in Certo
  today: split it, or check that part yourself.

## `incomplete`

Not given since 0.2.3. Before, it meant the agent's own to-do list still
had open items after Certo asked it to finish them. Now the project's
checks decide; a `verified` run with items still open says so in its
report ("the task may be unfinished"), and `certo --resume` continues it.

## `acceptance_failed`

Everything else passed, but a required
[acceptance check](acceptance-checks.md) failed. The failing check is
listed under the verdict. Certo doesn't send this back to the agent, so
resume with it:
`certo --resume "README.md needs a ## Usage section."`

If the check itself was wrong (a wrong path, or text that is too strict),
look at the file yourself: `certo verify` doesn't run acceptance checks.
Fix the check before you use it again.

## `independent_failed`

Only with `--independent-tests-strict`. The project's checks passed, but
most sets of [independent tests](independent-tests.md) failed. Each
set's failing tests are named under the verdict. Read them first: an
independent test can be wrong too.

- If the test is right, the work is wrong: resume with what the test
  expects, e.g. `certo --resume "A transfer's two amounts must have
  opposite signs."` Certo doesn't send the tests to the agent.
- If the test is wrong, the work may be fine: the project's own checks
  passed. With `CERTO_ARTIFACTS_DIR` set, the tests are kept in the run's
  record folder so you can check them.

## `budget_exhausted`

The task's time budget (`CERTO_MAX_TASK_SECONDS`, 30 minutes by default)
ran out, and the work so far couldn't be shown to pass: either the
checks failed, or the time ran out before a fix attempt. (If the budget
runs out during the agent's last step and the checks then pass, the
verdict is `verified`.) The work so far is in the folder.

- `certo --resume` continues with a fresh time budget.
- If every step is slow, the model is probably too big for your machine:
  see [Every step is very slow](../troubleshooting.md#every-step-is-very-slow).
- If the task is simply big, split it, or raise `CERTO_MAX_TASK_SECONDS`.

## `cost_exhausted`

The task reached its cost limit (`CERTO_MAX_TASK_COST`), and the work so
far couldn't be shown to pass. Certo stopped the agent at its next step,
then ran the checks once. The work so far is in the folder.

- Look at the run summary's `Total cost` and at `.certo/STATUS.md` to
  see how far it got.
- `certo --resume` continues with a fresh limit, perhaps with a hint so it
  needs fewer steps.
- If the task is simply big, split it, raise the limit, or use a cheaper
  `--model` for it.

## `stuck`

The agent's run ended stuck (the agent repeated itself) or in an error,
before it finished. Certo didn't check a run that broke off. (A run that
only used all its steps is checked; it ends `stuck` only when nothing
could be checked. If your model often needs more than 50 steps, raise
`CERTO_MAX_ITERATIONS`.)

- Resume once: `certo --resume`, perhaps with a hint.
- With a local model, check the context window first: a model that can't
  see the start of the task any more goes round in circles (see
  [The agent behaves erratically with Ollama](../troubleshooting.md#the-agent-behaves-erratically-with-ollama)).
- If it happens again, use a stronger `--model`.

## `confirmation_required`

Confirm mode (`CERTO_CONFIRM_MODE=always`) needed an approval and nobody
could give it, which happens in server mode. Run the task from the
`certo` command, where you can answer, or turn confirm mode off for
server tasks. See [Interactive and confirm mode](interactive-mode.md).

## With escalation

With `--escalate`, Certo already moves a failing task to the next, stronger
model by itself (see
[what makes Certo climb](escalate-between-models.md#what-makes-certo-climb)).
When the last model also fails, the advice above applies to its verdict.
`--resume` can't be combined with `--escalate`; resume with `--model` set
to the model you want.

## Related

- [Verdicts](../reference/verdicts.md): every verdict and exit code.
- [Resume an interrupted run](resume-a-run.md)
- [Write a task Certo can check](write-a-good-task.md)
- [Troubleshooting](../troubleshooting.md)
