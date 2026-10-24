# Verify in CI

This guide shows how to use Certo's verification in scripts and CI
pipelines: `certo verify` to check any project with no model, and the exit
codes of an agent run. It is for people who want a hard pass or fail
signal.

## `certo verify`: checks with no agent and no model

```bash
certo verify                  # the current folder
certo verify path/to/project
```

It runs exactly the checks Certo runs after an agent finishes: it detects
the project type, prepares the project's environment, then runs its tests,
build, lint and type checks. It needs no model, no API key, and reads no
`.env`. It runs once, with no retries, because there is no agent to send a
failure to.

A failing project:

```console
$ certo verify todo
Project: /home/me/todo (python)
  failed      pytest  (/home/me/todo/.venv/bin/python -m pytest -q)

--- pytest output ---
F                                                                        [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(2, 2) == 4
E       assert 0 == 4
E        +  where 0 = add(2, 2)

test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED test_calc.py::test_add - assert 0 == 4
1 failed in 0.01s

Verification: failed
```

The output has: the project type, any setup notes (lines starting with
`Certo:`), one line per check with its status and command, the output of
each failing check, then the verdict.

## Exit codes

| Verdict | Exit code | With `--require-verification` |
|---|---|---|
| `verified` | 0 | 0 |
| `inconclusive` | 0 | **1** |
| `failed`, `timed_out` | 1 | 1 |

`inconclusive` means nothing could be checked: no tests yet, an unknown
project type, or a missing tool. By default that is not a failure, because
nothing was shown to be broken. In CI you usually want proof that it
works, so add the flag:

```bash
certo verify --require-verification
```

For a standalone HTML page, for example, the plain command exits 0 and the
flag makes it exit 1.

## What CI needs installed

Certo runs the project's own tools; it doesn't install toolchains. Install
the ones your project uses in the CI job: Node and npm, Go, Rust (cargo),
Maven or Gradle. A missing tool makes the check `unavailable`, and the
verdict `inconclusive`.

For Python, Certo creates the project's `.venv` and installs pytest into
it when the project has tests but no pytest. That needs network access.

## Example: GitHub Actions

```yaml
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.3.0
      - run: uv tool install certo
      - run: certo verify --require-verification
```

## Agent runs in scripts

An agent run (`certo "<task>"`) uses the same rule: exit code 0 for
`verified` and `inconclusive`, 1 for every failure verdict and for errors.
`--require-verification` makes `inconclusive` exit 1 there too. The last
`Verification:` line names the verdict if you need more than the exit
code. Every verdict and its exit code is in
[Verdicts](../reference/verdicts.md).

## Related

- [Verify before every commit](verify-before-commit.md): run the same checks from a git hook
- [Make your project checkable](make-a-project-checkable.md)
- What runs for each language: [Verification by language](../reference/verification-by-language.md)
- [How verification works](../concepts/how-verification-works.md)
- Your own pass/fail rules: [Acceptance checks](acceptance-checks.md)
