# Verification by language

What Certo checks for each kind of project, and which files decide the
project type. It is for looking things up. Certo only runs commands that
the project itself sets up; it never invents one.

## How Certo finds the project

Certo looks for these files in the folder, then in subfolders up to four
levels down, skipping folders such as `node_modules`, `.git`, `.venv`,
`venv`, `dist` and hidden folders:

| Project type | Files |
|---|---|
| Python | `pyproject.toml`, `setup.py`, `setup.cfg` |
| Node / JavaScript / TypeScript | `package.json` |
| Go | `go.mod` |
| Rust | `Cargo.toml` |
| Java with Maven | `pom.xml` |
| Java with Gradle | `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts` |

- A file in the folder itself always wins. If one folder has several (for
  example `pyproject.toml` and `package.json`), the first row of the table
  wins.
- Otherwise the shallowest match wins. If two different folders match at
  the same depth (for example `frontend/` and `backend/`), the project is
  **ambiguous**: nothing is checked, the verdict is `inconclusive`, and the
  note names every candidate. Run Certo from the sub-project instead.
- With none of these files, a folder with `.py` files is treated as
  Python. The checks run from the folder that holds every folder with
  `.py` files: for a `game/` package and a `tests/` folder side by side,
  that is the folder above them.
- Otherwise the type is **unknown**: nothing is checked and the verdict is
  `inconclusive`. The note lists the files found.

## What runs

The main check decides `verified`. The other checks can only turn a pass
into a failure, never a failure into a pass.

| Project type | Main check | Other checks |
|---|---|---|
| Python | `pytest -q` | `ruff check .`, if ruff is configured; `mypy .`, if mypy is configured; for every program with an `if __name__ == "__main__":` block: the entry-point order check and `python <file>` |
| Node | `npm run build` if a `build` script exists, else `npm test` if a real `test` script exists | `npm test`, `npm run lint`, `npm run typecheck` (or `type-check`): each one only if the script exists and is not the main check |
| Go | `go test ./...` | `go vet ./...` |
| Rust | `cargo test` | `cargo check`, `cargo clippy` |
| Java (Maven) | `./mvnw test` if the wrapper exists, else `mvn test` | none |
| Java (Gradle) | `./gradlew test` if the wrapper exists, else `gradle test` | none |

A missing optional tool makes its check `unavailable`, never `failed`:
for example `cargo clippy` without the clippy component. The note under the
verdict names it.

Every check runs with no input (standard input closed) and a 300-second
time limit. A command that waits for input fails at once instead of
hanging.

## Python in detail

**Environment.** Every Python command runs with the project's own
interpreter, never Certo's. Certo uses the project's `uv.lock` (through
`uv run`) or a working `.venv/` or `venv/`, and creates `.venv` if there is
none. If there are test files (`test_*.py` or `*_test.py`) but no pytest,
Certo installs pytest into the project environment (5-minute limit). If
that fails, pytest is `unavailable`. See
[Work on an existing project](../guides/work-on-an-existing-project.md#python-projects-get-their-own-environment).

Virtual environments use `Scripts/python.exe` on Windows and `bin/python`
on macOS and Linux. Docker uses the container's Linux layout regardless of
the host OS.

**Configured** means:

- ruff: a `[tool.ruff]` section in `pyproject.toml`, or a `ruff.toml` or
  `.ruff.toml` file;
- mypy: a `[tool.mypy]` section in `pyproject.toml`, or a `mypy.ini` or
  `.mypy.ini` file.

ruff and mypy count only when installed in the project environment. Certo
doesn't install them. A configured but missing tool is a limitation, not a
failure. Other tools (flake8, pylint, pyright) are not run.

**Entry points.** Certo finds every `.py` file with a top-level
`if __name__ == "__main__":` block, up to four levels down, skipping
`tests/` and `test/` folders. For each one:

- **Entry-point order** (no command runs; Certo reads the file): the
  `__main__` block must be the last thing in the file. A function or class
  defined after it doesn't exist yet when the program runs, even though
  tests that import the file see it. This check exists because of a real
  bug; see [Why agents lie](../concepts/why-agents-lie.md).
- **`python <file>`** runs the program with no input. A file inside a
  package (a folder with `__init__.py`) runs as a module instead, the way
  such code is meant to run: `game/__main__.py` runs as `python -m game`,
  `game/cli.py` as `python -m game.cli`. It proves the
  program starts without crashing. It can't test menus or prompts, because
  nobody types anything. A program that crashes when input ends (an
  uncaught `EOFError`) fails this check.

## Node in detail

A `test` script that is npm's placeholder (`echo "Error: no test
specified" && exit 1`) doesn't count. `npm test`, `lint` and `typecheck`
run with `CI=true`, so test runners don't start in watch mode. Certo runs
the scripts as they are; it doesn't read jest or vitest settings.

If `package.json` has neither a `build` nor a real `test` script, the main
check is `unavailable` and the verdict is `inconclusive`.

When the main check is `npm test` and the runner exits successfully but
the output shows that no test ran, the check is `skipped` and the verdict
is `inconclusive`, not `verified` — the same treatment pytest's
"no tests collected" exit code already gets. Certo looks for
`node --test`'s zero-test summary line (in either of its two reporters:
`# tests 0` for TAP and `ℹ tests 0` for the spec reporter); Jest,
Vitest and Mocha already exit nonzero on an empty test run, so they
fail the check on their own. An extra `npm test` check that runs zero tests (when
`npm run build` is the main check) still does not change the verdict,
because an extra check can only turn a pass into a failure.

## Missing tools

When the tool for a project type isn't installed (`npm`, `go`, `cargo`,
`mvn` or `gradle`), its checks are `unavailable` and the verdict is
`inconclusive`. Install the tool, or run in an environment that has it.

## Not covered

Ruby, PHP, .NET, C and C++, and any other ecosystem are detected as
unknown. A standalone HTML or JavaScript page with no `package.json` is not
run: open it in a browser, or add a `package.json` with a `test` script.

## Related

- [Make your project checkable](../guides/make-a-project-checkable.md):
  how to set a project up for these checks.
- [Verdicts](verdicts.md)
- [How verification works](../concepts/how-verification-works.md)
