# How verification works

This page explains what Certo does after the agent says it is done, and
the rules behind each verdict. It is for readers who want to understand,
and trust, what `Verification: verified` means.

## The idea in one paragraph

The agent's final message is a claim. Certo treats it as one. When the
agent stops, Certo runs the project's own checks itself, as plain commands
with no AI involved. If something fails, Certo sends the real output back
to the agent and lets it try again. It stops when the checks pass, when
the retries run out, or when a fix attempt changes nothing. Then it prints
one verdict that the agent can't influence.

## The loop

```text
            ┌──────────────────────────────┐
 task ────► │ agent works until it stops   │ ◄─────────────┐
            └──────────────┬───────────────┘               │
                           ▼                               │
            stuck or error? ──────────────► stuck          │
                           ▼                               │
            open to-do items? ─────────► ask to finish ────┤
                           ▼                               │
            run the project's checks                       │
              all pass, a file changed ──► verified        │
              all pass, no file changed ─► ask once ───────┤
                still no file changed ───► unchanged       │
              nothing could run ─────────► inconclusive    │
              something failed:                            │
                same output as last time ► no_progress     │
                retries used up ─────────► retry_exhausted │
                otherwise: send the real output back ──────┘
```

Around all of this, a time budget (`CERTO_MAX_TASK_SECONDS`, 30 minutes by
default) is checked before every agent run, and stops a run that reaches
it. Acceptance checks, if you gave
any, run at the very end. The exact order is in
[Verdicts](../reference/verdicts.md#the-order-of-the-checks).

## What the agent gets back

When a check fails, the agent receives a message with the check's name,
its command, and its real output (the last 4,000 characters), plus
instructions:

- fix the cause, and don't weaken, skip, delete or disable the check;
- make a small edit where the output points, instead of rewriting the
  file;
- for a syntax error, fix only that line, and check that the file parses;
- for a timeout, look for an infinite loop or a wait, and don't just raise
  a timeout.

The agent keeps its whole conversation, so it knows what it already
tried.

## The rules behind the verdicts

**Certo never invents a command.** It only runs what the project sets up:
its test suite, its `build` script, a linter it configured. A project with
nothing to run gets `inconclusive`, never a guess. What runs for each
language is in [Verification by language](../reference/verification-by-language.md).

**"No tests" is not a pass.** Only the project's *main* check passing
gives `verified`. Finding nothing to run gives `inconclusive`, with a note
that says what was found. `inconclusive` exits 0 by default, because
nothing was shown to be broken; use `--require-verification` when you need
proof.

**Passing checks prove nothing if nothing changed.** If the project's
checks already passed before the agent started, a run that changed no file
would look like success. Certo asks the agent once, and if it still
changes nothing, the verdict is `unchanged`, not `verified`. See
[`unchanged`](../reference/verdicts.md#unchanged-in-more-detail).

**Passing checks prove less if the agent changed them.** An agent can
make tests pass by weakening them. After a `verified` run, Certo lists
each test or check settings file the agent changed or deleted, with the
lines changed, removed and added, so you can read them. The verdict stays, since
the task may have asked for the change. See
[Changed check files](../reference/verdicts.md#changed-check-files).

**Other checks can only make things worse.** Lint, type checks and the
Python start-up run can turn a pass into a failure, never a failure into a
pass. Tidy code is not proof that it works.

**A missing tool is a limitation, not a failure.** If ruff is configured
but not installed, or `go` is missing, the check is `unavailable`. It is
listed under the verdict, so you know what wasn't checked.

**A failure beats everything.** If any check fails, the result is a
failure, even if another check timed out or passed.

**A scratch file is pointed out.** When a failing check's output names a
file the agent created in this run whose name says it is scratch (such as
`.m6-smoke.mjs`, `edit_tmp.py` or `ui.js.new`), the fix message says so:
if the file was only for trying things out, the agent should delete it
instead of fixing it. Test files, files the task names and files the
acceptance checks ask for are never pointed out this way, so the message
can't push the agent to delete its tests or its work.

**No progress means stop.** After each fix attempt, Certo compares the
failing checks with the previous attempt: name, status, exit code and
output, with timings like `in 3.85s` removed. If they are identical, the
attempt provably changed nothing, and Certo stops with `no_progress`
instead of spending the remaining retries. It never tries to judge whether
the agent's explanation makes sense; only the output counts.

**A hang is not a wrong answer.** A check that runs longer than 300
seconds is stopped and retried like a failure. If it still hangs after the
retries, the verdict is `timed_out`, not `retry_exhausted`, because the fix
is usually different.

**Verification runs where the agent worked.** In Docker mode, Certo's
checks run inside the container, with the same tools and the same Python
environment as the agent.

## What Certo records

Every result carries a *completion contract*: the goal (the task text),
the acceptance criteria, the exact commands that were run, and the
limitations (what couldn't be checked). The `certo` command prints the
limitations under the verdict; server mode returns the whole contract;
`CERTO_ARTIFACTS_DIR` saves it to disk.

## What verification can't do

Be clear about the limits:

- **It only knows what the checks test.** If the tests don't cover a
  feature, a broken feature can still be `verified`. Certo makes the agent
  honest about the tests; it doesn't make the tests complete. When the
  agent writes the tests, they can share its mistakes:
  [independent tests](../guides/independent-tests.md), written before the
  build, are a second opinion (report only, unless you turn on
  `--independent-tests-strict`).
- **It goes by the check's exit code**, plus a count of the tests run
  where the output gives one (pytest, `node --test`, Jest, Vitest, Go,
  Cargo): none ran is `inconclusive`. A test runner Certo doesn't
  recognise that exits successfully with no tests still passes. See
  [Verification by language](../reference/verification-by-language.md#node-in-detail).
- **It can't drive interactive programs.** The Python start-up run has no
  input, so menus and prompts aren't exercised.
- **Some rules are only instructions.** Writing a `README.md`, using
  non-interactive tool options and not asking questions are prompt
  instructions the model can ignore.
- **Unknown project types aren't checked**, including standalone HTML
  pages.

`certo verify` runs the same checks without an agent, once, with no
retries. See [Verify in CI](../guides/verify-in-ci.md).

## Related

- [Why agents lie](why-agents-lie.md): the real cases behind these rules
- [Verdicts](../reference/verdicts.md)
- [Safety](safety.md)
