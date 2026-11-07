# Contributing

Issues and pull requests are welcome. When you open an issue, pick its
form: **Wrong verdict** is for a run where Certo said `verified` and the
work was wrong, or the reverse. Those are the most useful reports, since
a verdict you can trust is Certo's whole job. There are also forms for
bugs, feature requests and your own benchmark results.

For a question, an idea that isn't a feature request yet, or to show
what you ran Certo on, use
[Discussions](https://github.com/alessioricco/certo/discussions).

To work on the code:

```bash
git clone https://github.com/alessioricco/certo.git
cd certo
uv pip install -e ".[dev]"
uv run pytest -q     # no API key needed
```

See [`CLAUDE.md`](CLAUDE.md) for the project's working rules,
[`docs/`](docs/README.md) for how Certo behaves, and
[`ROADMAP.md`](ROADMAP.md) for where the project is going,
[`TODO.md`](TODO.md) for what's left to do,
[`DECISIONS.md`](DECISIONS.md) for the reasons behind design decisions,
and [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the code is built. To add a benchmark task, see
[Write or contribute a benchmark task](docs/guides/contribute-a-benchmark-task.md).

Three folders hold examples of different kinds:

- `src/certo/starter/tasks/`: the sample tasks. `certo init` copies them,
  with `src/certo/starter/README.md`, into a new workspace; they ship in
  the package. Add a sample there, and list it in that README and in
  `init_cmd.py` (`SAMPLES`, or `MILESTONE_SAMPLES` for one in milestones).
- `src/certo/examples/`: example settings files (`models.yaml.example`,
  `bench.yaml.example`...), which commands copy or point to.
- `examples/`: only the script that compares models on one task. Not in
  the package.

Task files of recorded runs live next to their record in `docs/benchmark/`.

If you work with Claude Code, download the skills this project uses
from [Anthropic's skills repository](https://github.com/anthropics/skills)
into `.claude/skills/` (git-ignored). The list and the pinned commit are
in the script, so everyone gets the same files. [`SKILLS.md`](SKILLS.md)
lists them and says why each one is used:

```bash
uv run python scripts/fetch_claude_skills.py
```

Only needed for Docker mode or server mode:

```bash
uv pip install -e ".[sandbox]"    # openhands-workspace, openhands-agent-server
uv pip install -e ".[server]"     # fastapi, uvicorn, httpx
```

`openhands-sdk` and `openhands-tools` are a matched set: always install or
upgrade both together, at the same version (see `pyproject.toml`).

## Tests

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

- CI (`.github/workflows/ci.yml`) runs the two ruff commands and the
  full suite, with the `server` extra and no API key, on every pull
  request and push to `main`, then `scripts/release_check.sh` on a freshly
  built wheel. The release workflow runs the same checks again: a lint,
  format or test failure blocks a release. The rules are named in `pyproject.toml`
  (`[tool.ruff.lint]`), so a ruff upgrade doesn't change them.
- `tests/` mirrors `src/certo/`. Tool executors are tested directly, with
  no model and no network.
- The end-to-end tests in `tests/test_runner.py` make real model calls and
  **skip** when `CERTO_LLM_MODEL`/`CERTO_LLM_API_KEY` aren't configured, so
  the suite passes with no key.
- Tests that need a toolchain (`npm`, `go`, `cargo`) skip when it is
  missing; tests about a tool being absent (`mvn`, `mypy`) skip when it is
  installed.
- The `server` and `sandbox` tests skip when those extras aren't
  installed.
- On Windows, symlink tests skip only when creating the link reports a
  missing symlink privilege (Developer Mode or `SeCreateSymbolicLinkPrivilege`).
  Directory-containment tests also run against real Windows junctions, which
  do not require that privilege. Unix permission checks run on macOS and Linux;
  Windows inherits folder ACLs instead of enforcing Unix mode `600`.
  CI runs the suite on `ubuntu-latest` and `windows-latest`.
- `tests/test_bench_tasks.py` checks every bundled benchmark task: its
  reference solution passes its hidden tests and its starter alone fails
  them. Adding a task: see `docs/guides/benchmark.md` ("Add a task").
- `tests/test_docs.py` keeps `docs/` honest: it fails when a `CERTO_*`
  setting, a command, subcommand or flag, or a verification state is
  missing from its reference page, or when a link between Markdown files
  is broken. If you add a setting or a flag, add it to
  `docs/reference/configuration.md` or `docs/reference/commands.md`.

### Release check (installed wheel)

The test suite runs inside the dev venv, where pytest and every dev tool
are installed. That once hid a real bug: Certo 0.1.0 verified projects with
its own interpreter, which only worked in the dev venv. So before a
release, check the wheel the way users install it:

```bash
scripts/release_check.sh                 # build the wheel, then check it
scripts/release_check.sh --wheel PATH    # check an already-built wheel
scripts/release_check.sh --with-llm      # also run a real agent task
```

It installs the wheel with `uv tool install` into a throwaway tool folder
and a throwaway `XDG_CONFIG_HOME`, and runs every command from an empty
temp folder, so no repo file, `.env` or user settings file is read. It
checks `certo --version` and `--help`; `certo init --yes --no-check` (the
user file with mode `600`, the sample folder without `.env`, a second
`init` refused, `certo check` naming the user file and reporting the
missing key, `init --local`, and `init` with no terminal); and
`certo verify` on three fixtures:

| Fixture | Expected |
|---|---|
| passing Python project | `Verification: verified`, exit `0` |
| failing Python project | `Verification: failed`, exit `1` |
| tests import a package installed only in the project's own `.venv` | `verified`, exit `0`; pytest installed into that `.venv`; nothing installed into Certo's own environment |

`--with-llm` also runs a real task with whatever `CERTO_LLM_*` variables
are exported and expects `Verification: verified`. The script needs `uv`
and network access. Run it directly, not through `uv run`. The release
workflow runs the non-LLM part against the exact wheel it publishes.

## Versioning

Each change that adds a feature bumps the third digit of the version
(`0.1.2` → `0.1.3`) in the same commit. The first two digits change only for
a deliberate bigger release. Update `version` in `pyproject.toml` and
`__version__` in `src/certo/__init__.py`, then run `uv lock`;
`tests/test_version.py` fails if the three disagree. `certo --version`
shows the installed version.

## Releasing

Releases are published to PyPI by `.github/workflows/release.yml` through
trusted publishing. There is no API token to manage.

1. Make sure the version in `pyproject.toml` is one PyPI has never seen.
   Features already bumped it (see Versioning); bump the third digit if
   only fixes went in since the last release. Run `scripts/release_check.sh`
   (add `--with-llm` with a model exported): it installs the wheel the way
   users do and checks it outside the dev venv.
2. Commit any change: `git commit -am "Release vX.Y.Z"`.
3. Tag and push: `git tag vX.Y.Z && git push && git push --tags`.
4. The workflow checks that the tag matches the version in
   `pyproject.toml`, runs the full test suite, builds the sdist and wheel,
   runs `twine check` and `scripts/release_check.sh` on that wheel, and
   publishes. A mismatch or a failing test stops it
   before anything is built.
5. After PyPI, the same workflow creates the GitHub Release, with
   `docs/launch/release-notes-vX.Y.Z.md` as its text (title removed,
   `../` links pointing at the tag). So the notes file must be final
   before the tag: replace its "Not released yet." line with the opening
   summary.

**A version number can never be reused.** PyPI rejects a re-upload of any
version that was ever published, even if it was deleted. If a release
comes out broken, fix it and release the next version.
