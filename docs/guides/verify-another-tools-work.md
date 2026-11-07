# Check another AI tool's work

This guide shows how to check the work of any coding tool (Claude Code,
Cursor, Aider, Copilot, or your own edits) with `certo verify`. It is for
people who use another tool to write code and want a verdict that doesn't
depend on what the tool says.

A coding tool often says "done" when the tests don't pass, or when there
are no tests at all. `certo verify` runs the project's own checks with no
model and no API key, and says what they show: `verified`, `failed` or
`inconclusive`.

## Run it after the tool finishes

When the tool says it has finished, run in the project's folder:

```bash
certo verify
```

or give the folder:

```bash
certo verify path/to/project
```

It finds the project type, prepares the project's own environment (a
Python project gets its `.venv`, with pytest if the tests need it), then
runs the tests, build, lint and type checks it finds. It checks the whole
project, not only the lines the tool changed, and never changes your code.
What runs for each language is in
[Verification by language](../reference/verification-by-language.md).

## A real example

Claude Code added a `fahrenheit_to_celsius` function to a small Python
project, with tests. To show both verdicts, its first version has a bug
put in on purpose, the kind these tools do make: the conversion factor the
wrong way round (`* 9 / 5` instead of `* 5 / 9`). The tests catch it, but
only when they run:

```console
$ certo verify temperature
Project: ~/code/temperature (python)
Certo: Created the project environment ~/code/temperature/.venv (/usr/local/bin/uv venv).
Certo: Installed pytest into the project environment ~/code/temperature/.venv (the project's tests need it and it wasn't there).
  failed      pytest  (~/code/temperature/.venv/bin/python -m pytest -q)

--- pytest output ---
..F                                                                      [100%]
=================================== FAILURES ===================================
_____________________________ test_back_to_celsius _____________________________

    def test_back_to_celsius():
        from temperature import fahrenheit_to_celsius
    
>       assert fahrenheit_to_celsius(212) == 100
E       assert 324.0 == 100
E        +  where 324.0 = <function fahrenheit_to_celsius at 0x1071550c0>(212)

test_temperature.py:15: AssertionError
=========================== short test summary info ============================
FAILED test_temperature.py::test_back_to_celsius - assert 324.0 == 100
1 failed, 2 passed in 0.01s

Verification: failed
```

The exit code is 1. Give the failing output back to the tool, or fix it
yourself. After the fix:

```console
$ certo verify temperature
Project: ~/code/temperature (python)
  passed      pytest  (~/code/temperature/.venv/bin/python -m pytest -q)

Verification: verified
```

The exit code is 0. (These are real runs, on 2026-11-07; the paths are
shortened.)

## Read the verdict

| Verdict | What it means for the tool's "done" | Exit code |
|---|---|---|
| `verified` | The project's checks ran and passed. | 0 |
| `failed` | A check failed: the work isn't done, whatever the tool said. The output of the failing check follows. | 1 |
| `inconclusive` | Nothing could be checked, so the tool's "done" isn't proven either way. | 0 (1 with `--require-verification`) |

`inconclusive` is the one to watch with AI tools. It isn't a failure:
nothing was shown to be broken. But nothing was shown to work either. A
single HTML page, for example:

```console
$ certo verify landing
Project: ~/code/landing (unknown)
  unavailable verification

Verification: inconclusive
  - verification: Found index.html — but no project manifest the harness recognizes (pyproject.toml, package.json, go.mod, Cargo.toml, pom.xml, build.gradle), so there was nothing it could run or test. The files exist; the result is unverified, not failed. Standalone HTML/JavaScript pages aren't executed by the harness: open the page in a browser to check it, or add a package.json with a `test` script to make it verifiable.
  - No automated check could be run for this project, so completion is unverified (not failed) — see the verification note for what was found.
```

The usual reasons are no tests yet, a project type Certo doesn't know, or
a missing tool (Node, Go, Rust...). The notes say which. To treat it as a
failure, for example in a script:

```bash
certo verify --require-verification
```

To make a project checkable, ask the tool to add tests and a manifest:
[Make your project checkable](make-a-project-checkable.md).

## Make it a habit

- Run it after every session with the tool, before you commit.
- Or let git do it: [Verify before every commit](verify-before-commit.md).
- Or let CI do it on every push: [Verify in CI](verify-in-ci.md).
- Many tools can run a command when they finish; point it at
  `certo verify`, so the tool sees the verdict too.

## Related

- [Verdicts](../reference/verdicts.md): every verdict and exit code
- [How verification works](../concepts/how-verification-works.md)
- [Why agents lie](../concepts/why-agents-lie.md): why a tool's "done" isn't proof
