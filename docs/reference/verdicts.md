# Verdicts

Every verdict (verification state) Certo can report, what it means, and
its exit code. It is for looking things up and for scripts. What to do
next after each one is in
[What to do after each verdict](../guides/after-the-verdict.md). Why Certo
works this way is in
[How verification works](../concepts/how-verification-works.md).

## Where you see the verdict

- **`certo`** prints `Verification: <verdict>` near the end, followed by
  any limitations as `-` lines.
- **`certo verify`** prints the same line.
- **Server mode** returns it as `verification_state` in
  `GET /tasks/{task_id}` and in the WebSocket `result` message. See
  [Server API](server-api.md).

## All verdicts

| Verdict | Meaning | Exit code |
|---|---|---|
| `verified` | The project's main check (its tests, or its build) ran and passed, and no other check failed. | 0 |
| `inconclusive` | Nothing could prove the work is right, and nothing proved it wrong. See below. | 0 (1 with `--require-verification`) |
| `unchanged` | The checks passed, but the agent changed no file in the project folder, even after Certo asked it once. The checks passed before the run too, so they don't show the task was done. See below. | 0 (1 with `--require-verification`) |
| `failed` | A check ran and failed. Only `certo verify` ends with this verdict; an agent run sends the failure back to the agent instead. | 1 |
| `retry_exhausted` | A check kept failing after `CERTO_MAX_VERIFY_RETRIES` fix attempts (2 by default), and the failure changed between attempts. | 1 |
| `no_progress` | A fix attempt changed nothing: the same check failed again with the same exit code and the same output (only timings may differ). Certo stops early instead of using up the retries. | 1 |
| `timed_out` | A check ran longer than 300 seconds and was stopped, and it still did after the fix attempts. Usually a program that hangs or waits for input. | 1 |
| `incomplete` | The agent's own to-do list still had open items after Certo asked it to finish them. Certo doesn't run the project's checks in this case. | 1 |
| `confirmation_required` | Confirm mode (`CERTO_CONFIRM_MODE=always`) needed an approval and nobody could give it (server mode). The action was rejected and the task stopped. | 1 |
| `budget_exhausted` | The task's time budget (`CERTO_MAX_TASK_SECONDS`, 30 minutes by default) ran out before the work could be shown to pass. If it ran out during the agent's last step, the checks still ran once, with no fix attempt; work that passed them is `verified` instead, unless the agent changed no file in the project folder. | 1 |
| `cost_exhausted` | The task's cost limit (`CERTO_MAX_TASK_COST`) was reached before the work could be shown to pass. As with the time budget, the checks still ran once, with no fix attempt; work that passed them is `verified` instead, unless the agent changed no file in the project folder. | 1 |
| `acceptance_failed` | Everything else passed, but a required [acceptance check](../guides/acceptance-checks.md) failed. | 1 |
| `independent_failed` | The checks passed, but most sets of [independent tests](../guides/independent-tests.md) failed. Only with `--independent-tests-strict` (`CERTO_INDEPENDENT_TESTS_STRICT=yes`); otherwise the result is only reported and the verdict stays `verified`. | 1 |
| `stuck` | The agent's run ended in a stuck or error state instead of finishing. Certo doesn't verify a run that broke off; `certo verify` checks the files it left. A run that used all its steps (`CERTO_MAX_ITERATIONS`) is checked instead, and ends `stuck` only when the checks can't show the task is done. | 1 |

The run itself can also fail before any verdict, for example with a
configuration error or a provider error. Then Certo prints
`Configuration error: ...` or `Error: ...` and exits 1.

## `inconclusive` in more detail

`inconclusive` is not a failure: nothing was shown to be broken. It is not
a pass either. It happens when:

- **The project has no tests yet.** For Python, no test files, or pytest
  found zero tests. This case is silent: no extra note.
- **The project type is unknown.** No `pyproject.toml`, `package.json`,
  `go.mod`, `Cargo.toml`, `pom.xml` or Gradle file, and no `.py` files.
  The note lists the files Certo found. A standalone HTML page lands here.
- **A required tool is missing**, such as `npm`, `go`, `cargo`, `mvn` or
  `gradle`, or pytest couldn't be installed.
- **The folder holds several projects** with no single one at the top. The
  note names them.
- **Verification is turned off** (`CERTO_VERIFY_TESTS=never`).

Use `--require-verification` (or `"require_verification": true` in server
mode) to treat `inconclusive` as a failure.

## `unchanged` in more detail

A project's checks can pass before the agent does anything: a "fix and
extend" task whose existing tests already pass is one example. If Certo
said `verified` there, a run in which the agent did nothing would look
like success. So after a `verified` run Certo compares the project folder
with how it was before the run:

- **A file was created, changed or deleted:** the verdict stays `verified`.
- **No file changed:** Certo asks the agent once to do the task, or to say
  why no change is needed. The agent may have stopped too early, or written
  its files somewhere else. If it then changes a file, Certo checks the
  project again as usual.
- **Still no change:** the verdict is `unchanged`. The agent's reason, if
  it gave one, is in its last message, but Certo doesn't take it as proof.

Some files never count as a change: Certo's own (`MODEL_DECISIONS.md`,
`.certo/`), environments and dependencies (`.venv`, `venv`,
`node_modules`), caches, and build output (`dist`, `build`, `target`,
`.gradle`).

`unchanged` is not a failure, because some tasks really need no change,
for example "check that the tests pass". Use `--require-verification` (or
`"require_verification": true` in server mode) to treat it as a failure.
A resumed run (`certo --resume`) never ends `unchanged`, since its changes
may come from the earlier session.

With [escalation](../guides/escalate-between-models.md#what-makes-certo-climb),
`unchanged` moves the task to the next model, unless the model before it
also changed no file: two models agreeing there is nothing to change
stops the climb. The same goes for `inconclusive` when the model changed
no file.

## Changed check files

`verified` means the project's checks passed after the run. An agent can
make checks pass by weakening them: editing a test, deleting one, or
turning a lint rule off. So before the run Certo keeps a copy of the
files the checks rely on, and after a `verified` run it lists each one
the agent changed or deleted, with the lines changed, removed and added:

```
Verification: verified
  - The agent changed 1 file the checks rely on: tests/test_calc.py (1 line changed). The checks passed on the changed files; read the changes before you trust them.
```

These files count: test files (in a `tests`, `test`, `__tests__` or
`spec` folder, or named like `test_*.py`, `*_test.go`, `*.test.ts`,
`*.spec.js`, `*Test.java`, `conftest.py`), and the settings files that
steer tests, build and lint (`pyproject.toml`, `setup.cfg`,
`pytest.ini`, `tox.ini`, `ruff.toml`, `mypy.ini`, `.flake8`,
`package.json`, `tsconfig*`, `jest.config*`, `vitest.config*`, ESLint
settings, `Cargo.toml`, `go.mod`, `pom.xml`, Gradle build files,
`Makefile`). New files aren't listed: adding tests is normal.

A line rewritten in place (an import that now imports one more name, a
corrected expected value) counts as changed, not removed. Removed lines
in a test are the ones to read first.

The verdict stays `verified`, since the task may have asked for the
change, as in the example above. On 379 saved benchmark runs, no run
removed a test line or deleted a test, including the 8 that fooled
Certo: see [Check files changed by benchmark runs](../benchmark/check-file-changes-0.1.24.md).

## The order of the checks

Certo checks, in this order, and stops at the first that applies:

1. Before and during every agent run (the first one and each retry): is
   the time budget used up? → `budget_exhausted`. Has the task cost
   `CERTO_MAX_TASK_COST`? → `cost_exhausted`. When the agent's last run
   ended after the budget or at the cost limit, the checks still run once,
   with no fix attempt, and passing work is `verified`. Did confirm mode need an
   answer nobody could give? → `confirmation_required`
2. After a run: did it end stuck or in error? → `stuck`. Not when the
   only error is that the agent used all its steps (`CERTO_MAX_ITERATIONS`):
   then Certo goes on to the checks below, as if the agent had finished.
   If they pass → `verified`; if they fail, the agent gets its fix
   attempts, each with a fresh set of steps; if nothing can be checked →
   `stuck`. A run `verified` this way, or after the time budget or the
   cost limit, carries a note that the task may be unfinished: the checks
   show that what the agent left works, not that it is all there.
   `certo --resume` with no `TASK` continues it.
3. Does the agent's to-do list have open items? Ask the agent to finish
   them; if they stay open → `incomplete`
4. Run the project's checks. On a failure, send it to the agent and check
   again → `verified`, `inconclusive`, `retry_exhausted`, `no_progress` or
   `timed_out`
5. After `verified`: did any file change? If not, ask the agent once and
   check again → may turn `verified` into `unchanged`. If the files the
   checks rely on changed, list them (the verdict stays)
6. Run the acceptance checks, if any → may turn `verified` into
   `acceptance_failed`
7. Run the independent tests, if on. With `--independent-tests-strict`,
   most sets failing turns `verified` into `independent_failed`

## Check statuses

Each single check (one command) also has a status. `certo verify` prints
it at the start of each line:

| Status | Meaning |
|---|---|
| `passed` | The command ran and succeeded. |
| `failed` | The command ran and failed. |
| `skipped` | Nothing to check here, e.g. no tests yet. Not a problem. |
| `unavailable` | It should be checkable but isn't, e.g. the tool isn't installed. Listed as a limitation. |
| `timed_out` | The command ran longer than 300 seconds and was stopped. |

How check statuses combine into a verdict is in
[How verification works](../concepts/how-verification-works.md).
