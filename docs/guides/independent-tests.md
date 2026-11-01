# Independent tests

This guide shows how to have Certo write tests for a task **before** the
agent builds it, and run them on the result. They check the agent's work
against the task, not against the agent's own tests.

> **Report only by default.** The result is printed next to the verdict,
> but it doesn't change the verdict or the exit code, because an
> independent test can itself be wrong. To let it change the verdict, see
> [Make them change the verdict](#make-them-change-the-verdict).

## Why

Certo's verdict comes from the project's own tests. When the agent writes
those tests, they can share its misunderstanding: a rule the task states
that neither the code nor the tests get right. Then the checks pass and
the verdict is `verified`, although the work is wrong. Independent tests
are written by someone who never saw the agent's work.

## Turn them on

```bash
certo tasks/ledger.md --project ledger --independent-tests
```

Or set `CERTO_INDEPENDENT_TESTS=yes` for every run. They work with one
model, `--auto-model` and `--escalate`, on local runs.

## What happens

1. **Before the build**, three separate, short conversations with the same
   model (with `--escalate`, the first model on the ladder) each read the
   task and a copy of the project as it is before the agent starts. Each
   writes its own *set* of tests for what the task states, or none when
   the task doesn't say what to call (a function, a command, an endpoint)
   or in which language.
2. **The tests stay outside the project** while the agent works, so the
   agent can't see, run or change them.
3. **After the verdict**, Certo copies each set into the project, runs
   it, and removes it again.
4. **The sets vote.** The result is `failed` only when most sets fail (2
   of 3). A wrong test usually turns up in one set only, so one failing
   set alone is reported as `split`.

They can be written in Python (pytest), Node (`node --test`), Go and Rust.
For a Go or Rust project the task must name the module or crate.

`CERTO_INDEPENDENT_TESTS_SETS` sets how many sets are written, from 1 to
5. Each set costs one more short conversation. With a cloud model they
are written at the same time; with a local one, one after another.

## What you see

From a real run (`ledger-transfers`, one of Certo's benchmark tasks, with
`claude-haiku-5-5`; the folder paths are shortened):

```text
Certo: writing 3 sets of independent tests from the task with anthropic/claude-haiku-5-5.
Certo: independent tests written in set 1 (test_parenthesized_amounts.py, test_store_uncategorized.py, test_transfer_report.py, test_transfers.py); the agent won't see them.
Certo: independent tests written in set 2 (test_bug_fixes.py, test_transfers.py); the agent won't see them.
Certo: independent tests written in set 3 (test_ledger_fixes.py, test_transfers.py); the agent won't see them.
[…]
Verification: verified
Independent tests: failed, 3 of 3 sets failed (written from the task by anthropic/claude-haiku-5-5; report only).
  - set 1: failed (1 failed, 22 passed in 0.04s): .certo_hidden_tests/test_transfers.py::test_outgoing_must_be_negative_and_incoming_positive[100.00--100.00]
  - set 2: failed (1 failed, 25 passed in 0.03s): .certo_hidden_tests/test_transfers.py::test_amounts_must_be_equal_and_opposite[100--100]
  - set 3: failed (1 failed, 14 passed in 0.03s): .certo_hidden_tests/test_transfers.py::test_amounts_must_match_in_size_currency_and_sign
```

In this run the agent's work was right (the task's hidden tests passed 27
of 27), and all three sets were wrong in the same way. The task defines
the outgoing side of a transfer by its negative amount; the tests called
one transaction "outgoing" by its name and expected a +100 there to stop
the match. When the task's words invite one misreading, most writers make
it, and voting doesn't help. That is why the result is a report, not a
verdict by default. When an independent test fails, read it before you
trust it either way.

Other results:

- `Independent tests: passed, …`: every set that ran passed.
- `Independent tests: split, 1 of 3 sets failed …`: a set failed, but
  not most of them. Often a wrong test, sometimes a real bug only one
  writer thought of; read the failing test.
- `Independent tests: none (…)`: no tests were written; the reason
  follows, often that the task names nothing to call.
- `Independent tests: couldn't run (…)`: the tests couldn't run, for
  example a missing toolchain.

With `CERTO_INDEPENDENT_TESTS_SETS=1` there is one set and no vote; the
line shows that set's own result.

## How often they're right

Measured on 379 projects from earlier benchmark runs, with
`claude-haiku-5-5` writing three sets of tests per task (see
[Independent tests on saved projects](../benchmark/independent-tests-replay-0.1.24.md)):

- They caught 7 of the 8 runs where Certo had said `verified` but the
  work was wrong.
- 5 of the 39 sets of tests had a test that read the task the
  wrong way, which then failed on right work too.
- Some failures on work the benchmark counted as right were real bugs,
  such as accepting `NaN` where the task asked for a number greater
  than 0.
- With "2 of 3 sets must fail", those wrong tests stopped counting
  (none of the 13 reference solutions failed) and 7 of the 8 were still
  caught.
- The vote doesn't help when most writers misread the task the same
  way, as in the run above.
- With the local `qwen3.8:27b` writing, the tests were milder: fewer
  false alarms, but with the vote they caught only 2 of the 8, and none
  of the real bugs. A weaker model writes weaker tests.

In 39 live benchmark runs with Haiku building and writing the tests (see
[Independent tests in live benchmark runs](../benchmark/independent-tests-live-0.1.24.md)):

- They failed 1 of the 38 runs whose work was right, and that failing
  test was wrong: it expected the wrong number of seconds for
  `"2h 5m 10s"`.
- Writing them took about 34 seconds per run, and the benchmark cost
  about twice as much as without them.
- The one run that fooled Certo broke a rule the task doesn't state, so
  tests written from the task couldn't catch it.

So read a failing independent test before you trust it either way.

## Make them change the verdict

```bash
certo tasks/ledger.md --project ledger --independent-tests-strict
```

Or set `CERTO_INDEPENDENT_TESTS_STRICT=yes`. Both turn the tests on. Now,
when the project's checks pass but most sets fail, the verdict is
`independent_failed` instead of `verified`, and Certo exits with 1:

```text
Verification: independent_failed
Independent tests: failed, 2 of 3 sets failed (written from the task by m).
```

(From Certo's tests; `m` is the model.) Only `failed` changes the
verdict: `split`, `none` and `couldn't run` leave `verified` as it is,
and so does a run that ended with any other verdict. With `--escalate`,
`independent_failed` doesn't climb to the next model: the tests are
run once, after the last model.

Use it where a script or a pipeline acts on the exit code and a false
`verified` costs more than a second look. Expect it to stop about one
right run in 40 with a wrong test (1 of 38 in the live runs above):
then read the failing test, and if it's wrong, keep the work. Since
0.1.25 the writer computes expected numbers in the test instead of by
hand, which removed the wrong sums behind most false alarms
([the replay](../benchmark/writer-arithmetic-0.1.25.md)).

## In the benchmark

To measure them on your own models, add `independent_tests: true` to an
arm in the [benchmark file](../reference/bench-yaml.md#arms):

```yaml
arms:
  - {name: haiku-independent, strategy: single, model: claude-haiku-5-5, independent_tests: true}
```

Each run then writes the tests before the build, and `results.md` shows
how often they failed, on right work and on runs that fooled Certo. See
[Read the results](benchmark.md#read-the-results).

## Keep the tests

With [`CERTO_ARTIFACTS_DIR`](../reference/configuration.md) set, the
tests are kept in the run's record folder, under `independent_tests/`
(one folder per set: `set1/`, `set2/`, …), so you can read the one that
failed. They are never left in the project,
where a later task's agent could see them.

## Costs and limits

- **Cost:** one extra short conversation per set, three by default.
  Their tokens and cost are part of the run summary. In the run above,
  the whole task cost $0.073.
- **Not on `--resume`**: the project already holds earlier work, so it
  isn't "before the build" any more. In [milestone mode](run-in-milestones.md#with-independent-tests),
  each milestone gets its own tests.
- **Not with `--execution docker`.** In server mode, a task asks for them
  with `independent_tests` (see [Server API](../reference/server-api.md#task-request-fields));
  over MCP, `run_task` does (see [Use Certo over MCP](use-certo-over-mcp.md#the-tools)).
  The JSON result shows them in `independent_tests`.
- **Vague tasks get none.** The writer only tests what the task or the
  existing code names; it doesn't guess. See
  [Write a good task](write-a-good-task.md).

## Related

- [How verification works](../concepts/how-verification-works.md)
- [Acceptance checks](acceptance-checks.md): your own pass or fail rules.
- [Configuration](../reference/configuration.md): `CERTO_INDEPENDENT_TESTS`,
  `CERTO_INDEPENDENT_TESTS_STRICT`.
