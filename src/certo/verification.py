"""Verification: check that a project actually works, with no model.

Language-neutral verification, in four explicit stages (see MANUAL.md "Test
verification"):

1. **Project detection** (`detect_project`) — what kind of project is this,
   and from which directory should commands run.
2. **Verification-plan discovery** (`discover_verification_plan`) — given a
   detected project, which commands apply, resolved against what the
   project itself configures — never invented. Pure/no subprocess calls:
   deciding *what* to run is kept separate from actually running it.
3. **Verification command execution** (`execute_check`) — runs one planned
   check and turns it into a structured `CheckOutcome`. The only stage that
   spawns a subprocess.
4. **Structured verification results** (`CheckOutcome` / `VerificationRun`) —
   the result shape both the harness's post-hoc loop (`runner.py`) and this
   module's own `run_full_verification()` orchestration consume.

Originally Python(pytest)/Node(`npm run build`)-only. Added after a live
failure where a scaffolded Vite/React project had a JSX syntax error
(`App.tsx` had adjacent, unwrapped JSX elements); the agent declared the
site "set up successfully" and pytest-only verification silently reported
"no tests collected" (exit code 5, treated as "nothing to verify") for the
exact same project — a false pass on code that didn't even compile.
Generalized to Go/Rust/Java(Maven+Gradle) plus Python/Node lint+typecheck
and Node lint/typecheck scripts per explicit follow-up request — see
DECISIONS.md for what's genuinely verified vs. only detected.
"""

from __future__ import annotations

import ast
import json
import os
import tomllib
from dataclasses import dataclass, field

from certo.project_env import (
    _MAX_SCAN_DEPTH,
    _SKIP_DIRS,
    CommandRunner,
    LocalRunner,
    ProjectEnv,
    available_modules,
    ensure_project_env,
    has_test_files,
    install_into_env,
)

# pytest's own exit code for "ran cleanly but collected zero tests" — not a
# failure, just nothing to verify (a project with no tests yet). Every other
# nonzero exit code means tests actually ran and something is wrong. No
# leading underscore: runner.py needs this same constant — see MANUAL.md
# "Test verification".
PYTEST_NO_TESTS_COLLECTED = 5

# `node --test`'s zero-test summary when it finds no test files — the runner
# exits 0 all the same, so a successful `npm test` whose output carries this
# marker is "skipped", not "passed" (issue #23). The bare "tests 0" matches
# the summary line in both reporters: TAP ("# tests 0", the one used without
# a terminal) and the spec reporter ("\u2139 tests 0", what Node 22+/26
# prints even through a pipe). A test file deliberately printing the exact
# string could masquerade as a zero-test run, but that errs toward
# "inconclusive", never toward a false "verified".
NODE_TEST_NO_TESTS_MARKER = "tests 0"

# `_SKIP_DIRS` (large, irrelevant directories such as node_modules and the
# project's own `.venv`/`venv`) and `_MAX_SCAN_DEPTH` live in project_env.py,
# shared with its own walks. The depth bound exists because a scaffolded
# project can land a level or two below the workspace root passed via
# --project — confirmed live: `npm create vite@latest ...` nested the actual
# app under <project>/<name>/<name>/ — without turning every verification
# call into a full tree walk.

# Marker files that unambiguously identify a project's language/ecosystem,
# checked in this order (so, e.g., a directory with both `pyproject.toml`
# and `package.json` is treated as Python — an unscoped monorepo edge case,
# not a real per-project decision). Each of these is a *single* well-known
# manifest format per ecosystem, which is what "unambiguous" means here —
# deliberately not extended to every possible build tool.
_LANGUAGE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("python", ("pyproject.toml", "setup.py", "setup.cfg")),
    ("node", ("package.json",)),
    ("go", ("go.mod",)),
    ("rust", ("Cargo.toml",)),
    ("java-maven", ("pom.xml",)),
    ("java-gradle", ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")),
)


@dataclass(frozen=True)
class ProjectDetection:
    """Stage 1 result: what kind of project this is, and where its
    verification commands should run from.

    `candidates` is only set when `language == "ambiguous"`: every
    (language, root) pair found at the shallowest depth where more than one
    distinct directory matched, so a caller/message can name them instead of
    silently picking one (see `detect_project`'s docstring).
    """

    # "python" | "node" | "go" | "rust" | "java-maven" | "java-gradle" |
    # "ambiguous" | "unknown"
    language: str
    root: str
    candidates: tuple[tuple[str, str], ...] | None = None


def detect_project(working_dir: str) -> ProjectDetection:
    """Detect the project's language/ecosystem from unambiguous manifest
    markers — a single depth-bounded tree walk checking every known
    ecosystem's markers together (not one walk per language), collecting
    every match grouped by depth so the *truly* shallowest directory/
    directories can be compared, rather than whichever one a top-down
    `os.walk` happens to visit first (a DFS visits an entire first branch,
    however deep, before a shallower sibling branch — "first found" and
    "shallowest" are not the same thing).

    If `working_dir` itself matches (depth 0), that's authoritative and
    returned immediately — the caller already told us this exact directory
    is the project (e.g. `CERTO_WORKSPACE`/`--project`), so there is
    nothing to disambiguate even if deeper subdirectories also happen to
    contain manifests (a project's own vendored dependency, a nested
    example, etc.).

    Otherwise, once the shallowest depth containing any match is found: if
    exactly one directory matched there, that's the project, same as
    before. If *multiple distinct directories* matched at that same
    shallowest depth — a monorepo/workspace with more than one candidate
    project and no single obvious root — this reports `"ambiguous"` with
    every candidate listed on `.candidates`, rather than silently choosing
    one based on directory-walk/listing order. (A single directory matching
    more than one language's markers, e.g. both `pyproject.toml` and
    `package.json` in the same directory, is a different, narrower case and
    is still resolved by `_LANGUAGE_MARKERS` order — not what "ambiguous"
    means here.)

    Falls back to "python" when no manifest is found but real Python source
    is present (`*.py` files) — this is what keeps a bare directory of
    `test_*.py` files (this repo's own test fixtures, and plenty of small
    real scripts with no `pyproject.toml`) working exactly as before. The
    root is then the deepest directory containing every directory that has
    `.py` files, not the first one the walk visits: confirmed live, a
    manifest-less `hanoi/` package plus a sibling `tests/` was otherwise
    rooted at the package, so pytest collected nothing. Only
    when *neither* a manifest *nor* any Python source is found does this
    report `"unknown"` — verification-plan discovery turns that into an
    explicit "verification unavailable" result rather than silently
    guessing a command (see `discover_verification_plan`).
    """
    base_depth = working_dir.rstrip(os.sep).count(os.sep)
    matches_by_depth: dict[int, list[tuple[str, str]]] = {}
    python_source_dirs: list[str] = []
    for root, dirs, files in os.walk(working_dir):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= _MAX_SCAN_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        if depth == 0:
            for language, markers in _LANGUAGE_MARKERS:
                if any(marker in files for marker in markers):
                    return ProjectDetection(language=language, root=root)
        else:
            for language, markers in _LANGUAGE_MARKERS:
                if any(marker in files for marker in markers):
                    matches_by_depth.setdefault(depth, []).append((language, root))
                    break  # one match per directory — same-dir ties are not "ambiguous"
        if any(f.endswith(".py") for f in files):
            python_source_dirs.append(root)
    if matches_by_depth:
        shallowest = matches_by_depth[min(matches_by_depth)]
        if len(shallowest) == 1:
            language, root = shallowest[0]
            return ProjectDetection(language=language, root=root)
        return ProjectDetection(
            language="ambiguous", root=working_dir, candidates=tuple(shallowest)
        )
    if python_source_dirs:
        return ProjectDetection(language="python", root=os.path.commonpath(python_source_dirs))
    return ProjectDetection(language="unknown", root=working_dir)


def _last_nonblank_line(output: str) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


# --- Harness-side, multi-check verification (not exposed to the LLM) -------
#
# The agent-facing `run_tests` tool (custom_tools/run_tests_tool.py) always
# runs exactly one check —
# that contract stays stable and unit-tested as-is. Everything below is the
# language-neutral pipeline the harness itself drives post-hoc, outside any
# tool-call round trip: stage 2 (verification-plan discovery, pure — no
# subprocess calls) decides *what* to run per detected language, stage 3
# (command execution) actually runs it, and stage 4 (these result types)
# aggregates. See runner.py's verification loop for how this feeds the
# retry/completion-contract logic.

# The five outcomes a single check can end in. "skipped" is a check that
# was never even attempted because it doesn't apply here (no lint config,
# no test script defined) *or* ran but found nothing to verify (pytest
# collected zero tests) — a legitimate, non-alarming absence. "unavailable"
# is a check that *should* have been attempted but couldn't be — its tool
# isn't installed, or (for the project's one synthetic "verification" check
# on an unknown project) no known command could be inferred at all. Never
# conflate the two: "skipped" isn't a limitation worth reporting; every
# "unavailable" is.
CHECK_STATUSES = ("passed", "failed", "skipped", "unavailable", "timed_out")


@dataclass(frozen=True)
class CheckOutcome:
    """One executed (or deliberately skipped/unavailable) verification check."""

    name: str  # e.g. "pytest", "ruff", "go test", "cargo clippy"
    command: str  # the actual command line, for the completion contract
    primary: bool  # the project's main test/build check vs. a secondary one
    status: str  # one of CHECK_STATUSES
    exit_code: int | None  # None when status is "skipped"/"unavailable"
    project_root: str
    summary: str
    output: str


@dataclass(frozen=True)
class VerificationRun:
    """The aggregate result of every check attempted for one verification pass."""

    checks: list[CheckOutcome]
    # Things the harness did to the project while setting up, worth telling
    # the user (e.g. "created .venv", "installed pytest into it").
    notices: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        """'failed' if anything actually ran and came back nonzero (highest
        priority — never let a timeout or a pass elsewhere hide a real
        failure); else 'timed_out' if anything exceeded its timeout; else
        'verified' only if the project's *primary* check ran and passed —
        a secondary check (lint/typecheck) can only ever pull this down to
        'failed', never promote it to 'verified' on its own, since tidiness
        isn't proof the software works; else 'inconclusive'."""
        if any(c.status == "failed" for c in self.checks):
            return "failed"
        if any(c.status == "timed_out" for c in self.checks):
            return "timed_out"
        primary = next((c for c in self.checks if c.primary), None)
        if primary is not None and primary.status == "passed":
            return "verified"
        return "inconclusive"

    @property
    def failing(self) -> list[CheckOutcome]:
        return [c for c in self.checks if c.status == "failed"]

    @property
    def timed_out_checks(self) -> list[CheckOutcome]:
        return [c for c in self.checks if c.status == "timed_out"]

    @property
    def commands(self) -> list[str]:
        return [c.command for c in self.checks if c.command]

    @property
    def limitation_notes(self) -> list[str]:
        """One human-readable note per check the harness *should* have been
        able to verify but couldn't — e.g. "ruff is configured but not
        installed," or "no known project type was detected." Deliberately
        excludes "skipped" checks (not configured, or nothing to test) —
        those aren't gaps, they're a correct absence."""
        return [f"{c.name}: {c.summary}" for c in self.checks if c.status == "unavailable"]


@dataclass(frozen=True)
class CheckSpec:
    """Stage 2 result: one planned verification check, not yet executed.

    `command=None` means nothing will run — either `skip_reason` (not
    applicable/configured) or `unavailable_reason` (should be checkable but
    isn't, e.g. a missing tool) explains why, and `execute_check` turns
    that directly into a "skipped"/"unavailable" `CheckOutcome` with no
    subprocess call at all.
    """

    name: str
    primary: bool
    command: list[str] | None
    cwd: str
    # Extra environment variables on top of the runner's own environment
    # (e.g. CI=true, or the project venv's VIRTUAL_ENV/PATH) — never a full
    # copy of this process's environment, which wouldn't apply inside a
    # Docker container anyway.
    env: dict[str, str] | None = None
    # Exit codes that mean "ran, found nothing to verify" rather than pass
    # or fail — pytest's PYTEST_NO_TESTS_COLLECTED is the only current use.
    skip_exit_codes: tuple[int, ...] = ()
    skip_reason: str | None = None
    unavailable_reason: str | None = None
    # Text that, in the output of a nonzero exit, means the tool itself is
    # missing rather than that the project failed it, e.g. cargo's "no such
    # command: `clippy`". The check is then "unavailable", not "failed".
    missing_tool_markers: tuple[str, ...] = ()
    missing_tool_reason: str | None = None
    # Text that, in the output of a *successful* run, means the tool ran but
    # found nothing to verify — `node --test`'s TAP reporter prints
    # "# tests 0" and still exits 0 when no test files exist. The check is
    # then "skipped" rather than "passed", so a project with no tests
    # cannot end `verified` with nothing tested (the pytest analogue is
    # `skip_exit_codes`; Jest, Vitest and Mocha already exit nonzero on an
    # empty test run, so only the built-in runner needs the marker today).
    no_work_markers: tuple[str, ...] = ()
    no_work_reason: str | None = None
    # A check whose result is already known at planning time — a pure
    # static check (e.g. an AST-based structural check) needs no subprocess
    # at all. `execute_check` returns this directly when set; `command`
    # must be None alongside it.
    precomputed: CheckOutcome | None = None


_CHECK_TIMEOUT_SECONDS = 300


def execute_check(
    spec: CheckSpec,
    *,
    timeout: int = _CHECK_TIMEOUT_SECONDS,
    runner: CommandRunner | None = None,
) -> CheckOutcome:
    """Stage 3: run one planned check. The only function in this module that
    spawns a subprocess for harness-side verification — except a
    `precomputed` spec, which by definition needed none. `runner` decides
    where: a host subprocess by default, or inside the Docker container (see
    project_env.WorkspaceRunner). Either way stdin is closed: no human is
    available to answer a prompt (same rationale as agent.py's
    _NONINTERACTIVE_TOOLING_SUFFIX), so a command that reads stdin fails
    fast instead of hanging, which is also what lets the entry-point smoke
    check observe how a script behaves with no input available."""
    if spec.precomputed is not None:
        return spec.precomputed
    if spec.command is None:
        status = "unavailable" if spec.unavailable_reason else "skipped"
        summary = spec.unavailable_reason or spec.skip_reason or f"{spec.name} does not apply here"
        return CheckOutcome(
            name=spec.name,
            command="",
            primary=spec.primary,
            status=status,
            exit_code=None,
            project_root=spec.cwd,
            summary=summary,
            output="",
        )

    runner = runner or LocalRunner()
    command_str = " ".join(spec.command)
    result = runner.run(spec.command, cwd=spec.cwd, env=spec.env, timeout=timeout)
    if result.timed_out:
        return CheckOutcome(
            name=spec.name,
            command=command_str,
            primary=spec.primary,
            status="timed_out",
            exit_code=None,
            project_root=spec.cwd,
            summary=f"{spec.name} exceeded its {timeout}s timeout and was killed",
            output=result.output[-4000:],
        )
    if result.returncode is None:
        return CheckOutcome(
            name=spec.name,
            command=command_str,
            primary=spec.primary,
            status="unavailable",
            exit_code=None,
            project_root=spec.cwd,
            summary=f"{spec.name} could not be run: {result.error}",
            output="",
        )

    output = result.output
    if result.returncode in spec.skip_exit_codes:
        return CheckOutcome(
            name=spec.name,
            command=command_str,
            primary=spec.primary,
            status="skipped",
            exit_code=result.returncode,
            project_root=spec.cwd,
            summary=spec.skip_reason or f"{spec.name}: nothing to verify",
            output="",
        )
    passed = result.returncode == 0
    if passed and any(m in output for m in spec.no_work_markers):
        return CheckOutcome(
            name=spec.name,
            command=command_str,
            primary=spec.primary,
            status="skipped",
            exit_code=result.returncode,
            project_root=spec.cwd,
            summary=spec.no_work_reason or f"{spec.name}: ran, but found nothing to verify",
            output=output[-4000:],
        )
    if not passed and any(m in output for m in spec.missing_tool_markers):
        return CheckOutcome(
            name=spec.name,
            command=command_str,
            primary=spec.primary,
            status="unavailable",
            exit_code=None,
            project_root=spec.cwd,
            summary=spec.missing_tool_reason or f"{spec.name} is not installed",
            output=output[-4000:],
        )
    summary = f"{spec.name} {'passed' if passed else f'failed (exit {result.returncode})'}"
    return CheckOutcome(
        name=spec.name,
        command=command_str,
        primary=spec.primary,
        status="passed" if passed else "failed",
        exit_code=result.returncode,
        project_root=spec.cwd,
        summary=summary,
        output=output[-4000:],
    )


def _pyproject_has_tool_section(run_dir: str, section: str) -> bool:
    path = os.path.join(run_dir, "pyproject.toml")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return section in data.get("tool", {})


def _ruff_configured(run_dir: str) -> bool:
    return (
        _pyproject_has_tool_section(run_dir, "ruff")
        or os.path.isfile(os.path.join(run_dir, "ruff.toml"))
        or os.path.isfile(os.path.join(run_dir, ".ruff.toml"))
    )


def _mypy_configured(run_dir: str) -> bool:
    return (
        _pyproject_has_tool_section(run_dir, "mypy")
        or os.path.isfile(os.path.join(run_dir, "mypy.ini"))
        or os.path.isfile(os.path.join(run_dir, ".mypy.ini"))
    )


def _node_scripts(run_dir: str) -> dict[str, str]:
    path = os.path.join(run_dir, "package.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("scripts", {})
    except (OSError, ValueError):
        return {}


def _real_node_script(scripts: dict[str, str], key: str) -> str | None:
    """A `package.json` script worth running, or None — filters out
    `npm init`'s default placeholder test script
    (`"echo \\"Error: no test specified\\" && exit 1"`), which always
    "fails" and would report a false regression for a project that simply
    never defined tests."""
    script = scripts.get(key)
    if not script or "no test specified" in script.lower():
        return None
    return script


def _npm_test_script(run_dir: str) -> str | None:
    return _real_node_script(_node_scripts(run_dir), "test")


# --- Python entry-point checks ----------------------------------------------
#
# A passing pytest suite only proves the code behaves correctly when
# *imported* — confirmed live this is a real, distinct gap: a script defined
# a function *after* its own `if __name__ == "__main__":` guard, and the
# function it called only when a particular interactive command was chosen.
# Importing the module (exactly what a test suite does) runs the whole file
# top-to-bottom and never enters the guarded block, so the function exists
# by the time any test could call it; running the script directly calls into
# the guarded block immediately, before the interpreter ever reaches that
# later definition — `NameError`, invisible to every test, visible to every
# real user. Two checks, from two different angles: `_entrypoint_ordering_spec`
# is a static, structural check for exactly this ordering mistake; the
# `python <entry point>` `CheckSpec`s built in `_python_plan` actually run
# each entry point (stdin closed — see `execute_check`) to catch startup
# crashes generally, this ordering bug included if it happens to fire before
# any input is read (not guaranteed — this one only reaches the guarded
# `main()` call, not necessarily the specific branch inside it that broke
# live; the static check is what caught that precisely).


def _is_main_guard(node: ast.stmt) -> bool:
    """True for `if __name__ == "__main__":` (either operand order)."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not (
        isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
    ):
        return False
    operands = (test.left, test.comparators[0])
    names = [o for o in operands if isinstance(o, ast.Name)]
    consts = [o for o in operands if isinstance(o, ast.Constant)]
    return (
        len(names) == 1
        and len(consts) == 1
        and names[0].id == "__name__"
        and consts[0].value == "__main__"
    )


# Directories entry-point discovery skips beyond the usual _SKIP_DIRS
# (vendored/build output): a project's own tests directory. Recursing at
# all was deliberately deferred until there was a real reason to (see
# DECISIONS.md) specifically because an unfiltered walk
# risks two kinds of false positive — a vendored dependency's own
# `__main__` guard (already covered by _SKIP_DIRS) and a test *script*
# that happens to define one too (e.g. `if __name__ == "__main__":
# unittest.main()`), which is not "the program's own entry point" in the
# sense this check cares about.
_ENTRYPOINT_SKIP_DIRS = _SKIP_DIRS | {"tests", "test"}


def _find_python_entrypoints(root: str) -> list[str]:
    """`.py` files under `root` whose top level contains a
    `if __name__ == "__main__":` guard — recursive, but depth-bounded
    (`_MAX_SCAN_DEPTH`, the same bound `detect_project()` uses: a
    scaffolded project's real code can land a level or two below the given
    root) and skipping known vendor/build directories plus a project's own
    tests directory (`_ENTRYPOINT_SKIP_DIRS`) — recursion without those
    exclusions would risk matching an unrelated `__main__` guard inside a
    vendored dependency or a test script, not the program's own entry
    point. Returns paths relative to `root` (a bare filename for a
    root-level entry point, unchanged from before this was recursive), so
    callers can `os.path.join(root, name)` or run `python <name>` with
    `cwd=root` exactly as they already do. Skips a file that fails to parse
    (a real syntax error surfaces via pytest collection instead).
    """
    entrypoints: list[str] = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for current_root, dirs, files in os.walk(root):
        depth = current_root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= _MAX_SCAN_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in _ENTRYPOINT_SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(current_root, name)
            try:
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=path)
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                continue
            if any(_is_main_guard(node) for node in tree.body):
                entrypoints.append(os.path.relpath(path, root))
    return sorted(entrypoints)


def _entrypoint_args(root: str, name: str) -> list[str]:
    """How to run one entry point from `root`: a file inside a package (its
    directory has `__init__.py`) as a module, `-m pkg` or `-m pkg.mod`, the
    way such code is meant to run; any other file by its path. Running
    `pkg/__main__.py` by path puts `pkg/` itself on `sys.path`, so the
    package's own absolute imports (`from pkg.cli import main`) fail —
    confirmed live, it pushed the agent into a `sys.path` workaround."""
    directory = os.path.dirname(name)
    if not directory or not os.path.isfile(os.path.join(root, directory, "__init__.py")):
        return [name]
    module = os.path.splitext(name)[0].split(os.sep)
    if module[-1] == "__main__":
        module = module[:-1]
    return ["-m", ".".join(module)]


def _entrypoint_ordering_spec(root: str, entrypoints: list[str]) -> CheckSpec | None:
    """A precomputed (no-subprocess) static check: for each detected entry
    point, is its `if __name__ == "__main__":` guard the file's *last*
    top-level statement? A `def`/`class` appearing after the guard won't
    exist yet when the script is run directly, even though it's fully
    defined by the time anything `import`s the module. Returns None only
    when there are no entry points to check at all — with at least one, this
    always contributes a check (`passed` or `failed`), the same way pytest
    always runs for a Python project; it isn't gated on project config,
    since it isn't optional/configurable, it's a language-level trap.
    """
    if not entrypoints:
        return None
    problems: list[str] = []
    for name in entrypoints:
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        guard_index = next((i for i, node in enumerate(tree.body) if _is_main_guard(node)), None)
        if guard_index is None:
            continue
        later_defs = [
            node.name
            for node in tree.body[guard_index + 1 :]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        if later_defs:
            problems.append(
                f'{name}: `if __name__ == "__main__":` is not the file\'s last '
                f"top-level statement — {', '.join(later_defs)} defined after it "
                "will not exist yet when this script is run directly, even though "
                "importing the module (what pytest does) sees it fine. Move the "
                "__main__ guard (and whatever it calls) to the end of the file, "
                "after every definition it needs."
            )
    outcome = CheckOutcome(
        name="entrypoint-ordering",
        command="",
        primary=False,
        status="failed" if problems else "passed",
        exit_code=None,
        project_root=root,
        summary=(
            "entry point defines something after its own __main__ guard"
            if problems
            else "entry point definition order OK"
        ),
        output="\n".join(problems),
    )
    return CheckSpec(
        name="entrypoint-ordering", primary=False, command=None, cwd=root, precomputed=outcome
    )


@dataclass
class PythonEnvState:
    """Result of the Python setup stage (`prepare_python_env`): the project's
    environment and what it can run. Planning (`_python_plan`) reads this
    instead of probing anything itself, so it stays subprocess-free."""

    env: ProjectEnv | None
    modules: set[str] = field(default_factory=set)
    # Why the environment, or pytest in it, isn't usable.
    pytest_unavailable_reason: str | None = None
    has_tests: bool = True
    notices: list[str] = field(default_factory=list)
    base_path: str = ""

    def env_vars(self) -> dict[str, str] | None:
        return self.env.env_vars(self.base_path) if self.env else None


def prepare_python_env(
    root: str,
    runner: CommandRunner | None = None,
    *,
    stop_at: str | None = None,
    install_pytest: bool = True,
) -> PythonEnvState:
    """Setup stage for a Python project (subprocesses allowed): find or
    create its environment, see which check tools it has, and install pytest
    into it when the project has tests but no pytest.

    The install goes into the project environment only, with stdin closed
    and a timeout. If it fails, pytest is reported unavailable with the
    reason — a missing test runner is a limitation, not a test failure.
    """
    runner = runner or LocalRunner()
    setup = ensure_project_env(root, runner, stop_at=stop_at)
    state = PythonEnvState(
        env=setup.env,
        notices=list(setup.notices),
        has_tests=has_test_files(root),
        base_path=runner.base_path(),
    )
    if setup.env is None:
        state.pytest_unavailable_reason = setup.unavailable_reason
        return state
    modules = available_modules(setup.env, runner, root)
    if modules is None:
        state.pytest_unavailable_reason = (
            f"the project environment's interpreter ({' '.join(setup.env.python)}) could not be run"
        )
        return state
    state.modules = modules
    if "pytest" in modules or not state.has_tests or not install_pytest:
        return state
    result = install_into_env(setup.env, runner, "pytest", root)
    if result.returncode == 0 and "pytest" in (available_modules(setup.env, runner, root) or set()):
        state.modules.add("pytest")
        state.notices.append(
            f"Installed pytest into the project environment {setup.env.host_dir} "
            "(the project's tests need it and it wasn't there)."
        )
        return state
    detail = _last_nonblank_line(result.error or result.output) or (
        "timed out" if result.timed_out else f"exit {result.returncode}"
    )
    state.pytest_unavailable_reason = (
        "pytest is not installed in the project environment "
        f"({setup.env.host_dir}) and installing it failed: {detail}"
    )
    return state


def _python_plan(root: str, state: PythonEnvState | None = None) -> list[CheckSpec]:
    """Every Python check runs with the project's interpreter (`state.env`),
    never this process's own. Without a prepared environment (`state` None)
    the test check is unavailable rather than guessed."""
    env_vars = state.env_vars() if state else None
    python = list(state.env.python) if state and state.env else None
    modules = state.modules if state else set()

    if python is None:
        reason = (state.pytest_unavailable_reason if state else None) or (
            "no project environment was prepared for this Python project"
        )
        specs = [
            CheckSpec(
                name="pytest", primary=True, command=None, cwd=root, unavailable_reason=reason
            )
        ]
    elif "pytest" not in modules and state is not None and not state.has_tests:
        specs = [
            CheckSpec(
                name="pytest",
                primary=True,
                command=None,
                cwd=root,
                skip_reason="no tests collected (no test files found)",
            )
        ]
    elif "pytest" not in modules:
        reason = (state.pytest_unavailable_reason if state else None) or (
            "pytest is not installed in the project environment"
        )
        specs = [
            CheckSpec(
                name="pytest", primary=True, command=None, cwd=root, unavailable_reason=reason
            )
        ]
    else:
        specs = [
            CheckSpec(
                name="pytest",
                primary=True,
                command=[*python, "-m", "pytest", "-q"],
                cwd=root,
                env=env_vars,
                skip_exit_codes=(PYTEST_NO_TESTS_COLLECTED,),
                skip_reason="no tests collected",
            )
        ]
    for tool, configured, what in (
        ("ruff", _ruff_configured(root), "lint"),
        ("mypy", _mypy_configured(root), "type checking"),
    ):
        if not configured:
            continue
        if python is not None and tool in modules:
            args = ["check", "."] if tool == "ruff" else ["."]
            specs.append(
                CheckSpec(
                    name=tool,
                    primary=False,
                    command=[*python, "-m", tool, *args],
                    cwd=root,
                    env=env_vars,
                )
            )
        else:
            specs.append(
                CheckSpec(
                    name=tool,
                    primary=False,
                    command=None,
                    cwd=root,
                    unavailable_reason=(
                        f"{tool} is configured but not installed in the project "
                        f"environment; {what} was not verified"
                    ),
                )
            )

    entrypoints = _find_python_entrypoints(root)
    ordering_spec = _entrypoint_ordering_spec(root, entrypoints)
    if ordering_spec is not None:
        specs.append(ordering_spec)
    # Actually run each entry point (not just import it, which pytest already
    # does) — stdin is closed (see execute_check), so this only proves the
    # script doesn't crash before/without reading input; it cannot exercise
    # an interactive menu path like a "SOLVE" command. That's a real,
    # deliberate scope limit, not an oversight — see MANUAL.md "Test
    # verification".
    if python is not None:
        for name in entrypoints:
            args = _entrypoint_args(root, name)
            specs.append(
                CheckSpec(
                    name=f"python {' '.join(args)}",
                    primary=False,
                    command=[*python, *args],
                    cwd=root,
                    env=env_vars,
                )
            )
    return specs


# npm scripts checked, in priority order for picking the *primary* check:
# a `build` script exists → build is primary (it's what actually catches a
# compile/parse error, per this tool's own history — see module docstring);
# else a real `test` script → test is primary. `lint`/`typecheck` are always
# secondary when present. Nothing here is invented: a script only becomes a
# check if the project's own package.json defines it.
def _node_plan(root: str, runner: CommandRunner) -> list[CheckSpec]:
    npm = runner.which("npm")
    scripts = _node_scripts(root)
    build = _real_node_script(scripts, "build")
    test = _real_node_script(scripts, "test")
    lint = _real_node_script(scripts, "lint")
    typecheck_key = "typecheck" if _real_node_script(scripts, "typecheck") else "type-check"
    typecheck = _real_node_script(scripts, typecheck_key)

    primary_key = "build" if build else ("test" if test else None)
    if primary_key is None:
        return [
            CheckSpec(
                name="npm run <build|test>",
                primary=True,
                command=None,
                cwd=root,
                unavailable_reason="package.json defines no build or test script",
            )
        ]

    def spec_for(key: str, *, primary: bool, use_ci_env: bool) -> CheckSpec:
        name = f"npm run {key}" if key != "test" else "npm test"
        if npm is None:
            return CheckSpec(
                name=name,
                primary=primary,
                command=None,
                cwd=root,
                unavailable_reason="npm not found on PATH",
            )
        command = [npm, "test"] if key == "test" else [npm, "run", key]
        # CI=true is the widely-adopted convention (CRA's react-scripts,
        # Vitest, Jest) for making a test/lint runner exit after one pass
        # instead of defaulting to an interactive watch mode with no human
        # to drive it — same rationale as agent.py's
        # _NONINTERACTIVE_TOOLING_SUFFIX, applied to the harness's own
        # subprocess calls. `build` isn't a watch-mode command, so it's
        # left out of this.
        env = {"CI": "true"} if use_ci_env else None
        no_work = (
            (NODE_TEST_NO_TESTS_MARKER,)
            if key == "test" and primary
            else ()
        )
        return CheckSpec(
            name=name,
            primary=primary,
            command=command,
            cwd=root,
            env=env,
            no_work_markers=no_work,
            no_work_reason="no tests ran (node --test found no test files)"
            if no_work
            else None,
        )

    specs = [spec_for(primary_key, primary=True, use_ci_env=primary_key != "build")]
    if primary_key != "test" and test:
        specs.append(spec_for("test", primary=False, use_ci_env=True))
    if lint:
        specs.append(spec_for("lint", primary=False, use_ci_env=True))
    if typecheck:
        specs.append(spec_for(typecheck_key, primary=False, use_ci_env=True))
    return specs


def _go_plan(root: str, runner: CommandRunner) -> list[CheckSpec]:
    go = runner.which("go")
    if go is None:
        return [
            CheckSpec(
                name="go test",
                primary=True,
                command=None,
                cwd=root,
                unavailable_reason="go is configured (go.mod present) but not installed",
            )
        ]
    return [
        CheckSpec(name="go test", primary=True, command=[go, "test", "./..."], cwd=root),
        CheckSpec(name="go vet", primary=False, command=[go, "vet", "./..."], cwd=root),
    ]


def _rust_plan(root: str, runner: CommandRunner) -> list[CheckSpec]:
    cargo = runner.which("cargo")
    if cargo is None:
        return [
            CheckSpec(
                name="cargo test",
                primary=True,
                command=None,
                cwd=root,
                unavailable_reason="cargo is configured (Cargo.toml present) but not installed",
            )
        ]
    return [
        CheckSpec(name="cargo test", primary=True, command=[cargo, "test"], cwd=root),
        CheckSpec(name="cargo check", primary=False, command=[cargo, "check"], cwd=root),
        CheckSpec(
            name="cargo clippy",
            primary=False,
            command=[cargo, "clippy"],
            cwd=root,
            # Without rustup, cargo has no clippy subcommand; with rustup but
            # without the component, its cargo-clippy proxy says so.
            missing_tool_markers=(
                "no such command: `clippy`",
                "is not installed for the toolchain",
            ),
            missing_tool_reason=(
                "clippy is not installed (with rustup: rustup component add clippy)"
            ),
        ),
    ]


def _wrapper_or_tool(
    root: str, wrapper_name: str, tool_name: str, runner: CommandRunner
) -> tuple[str | None, str | None]:
    """Prefer a checked-in wrapper script (`./mvnw`, `./gradlew`) over a
    globally installed tool — the "prefer checked-in wrappers" convention of
    this project's own `testing-and-verification` skill. Returns
    (executable, error) — exactly one is None."""
    wrapper = os.path.join(root, wrapper_name)
    if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
        return runner.exec_path(wrapper), None
    tool = runner.which(tool_name)
    if tool is not None:
        return tool, None
    return None, f"neither ./{wrapper_name} nor {tool_name} is available"


def _java_plan(detection: ProjectDetection, runner: CommandRunner) -> list[CheckSpec]:
    root = detection.root
    if detection.language == "java-maven":
        executable, error = _wrapper_or_tool(root, "mvnw", "mvn", runner)
        name = "mvn test"
        manifest = "pom.xml"
    else:
        executable, error = _wrapper_or_tool(root, "gradlew", "gradle", runner)
        name = "gradle test"
        manifest = "build.gradle"
    if executable is None:
        return [
            CheckSpec(
                name=name,
                primary=True,
                command=None,
                cwd=root,
                unavailable_reason=f"{manifest} is present but {error}",
            )
        ]
    return [CheckSpec(name=name, primary=True, command=[executable, "test"], cwd=root)]


def discover_verification_plan(
    detection: ProjectDetection,
    *,
    python_env: PythonEnvState | None = None,
    runner: CommandRunner | None = None,
) -> list[CheckSpec]:
    """Stage 2: given a detected project, decide which checks apply — pure
    (file reads and tool lookups only, no check execution). A Python
    project's environment comes from the setup stage (`python_env`, see
    `prepare_python_env`); `runner` resolves tool names where the checks
    will run (the host, or the Docker container).
    Never invents a check the project doesn't itself configure; an unknown
    project gets a single synthetic check explaining that plainly rather
    than a guessed command. An "ambiguous" detection (multiple candidate
    projects, no single obvious root — see `detect_project`) gets the same
    treatment: one synthetic, unavailable check naming every candidate,
    instead of silently verifying whichever one was found first.
    """
    runner = runner or LocalRunner()
    if detection.language == "python":
        return _python_plan(detection.root, python_env)
    if detection.language == "node":
        return _node_plan(detection.root, runner)
    if detection.language == "go":
        return _go_plan(detection.root, runner)
    if detection.language == "rust":
        return _rust_plan(detection.root, runner)
    if detection.language in ("java-maven", "java-gradle"):
        return _java_plan(detection, runner)
    if detection.language == "ambiguous":
        candidates = ", ".join(
            f"{root} ({language})" for language, root in (detection.candidates or ())
        )
        return [
            CheckSpec(
                name="verification",
                primary=True,
                command=None,
                cwd=detection.root,
                unavailable_reason=(
                    "Multiple candidate projects were found with no single "
                    f"obvious root — verification is ambiguous: {candidates}. "
                    "Point CERTO_WORKSPACE/--project at the specific "
                    "project to verify instead of the shared parent directory."
                ),
            )
        ]
    return [
        CheckSpec(
            name="verification",
            primary=True,
            command=None,
            cwd=detection.root,
            unavailable_reason=_describe_unrecognized_workspace(detection.root),
        )
    ]


_LISTED_FILES_LIMIT = 5
_WEB_PAGE_SUFFIXES = (".html", ".htm")


def _describe_unrecognized_workspace(root: str) -> str:
    """Explain an `"unknown"` detection in terms of what *is* there.

    "No known project type" alone reads as "no code was produced", which is
    wrong for e.g. a self-contained index.html with inline JavaScript: the
    files exist, the harness just has no check for them. So name the files
    actually found, the manifests that were looked for, and distinguish a
    genuinely empty workspace.
    """
    found: list[str] = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for current, dirs, files in os.walk(root):
        if current.rstrip(os.sep).count(os.sep) - base_depth >= _MAX_SCAN_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        found.extend(
            os.path.relpath(os.path.join(current, f), root)
            for f in sorted(files)
            if not f.startswith(".")
        )
    if not found:
        return "The workspace contains no files — nothing was produced for the harness to verify."
    listed = ", ".join(found[:_LISTED_FILES_LIMIT])
    if len(found) > _LISTED_FILES_LIMIT:
        listed += f", … ({len(found)} files in total)"
    # One representative manifest per ecosystem keeps the message readable.
    manifests = ", ".join(markers[0] for _, markers in _LANGUAGE_MARKERS)
    message = (
        f"Found {listed} — but no project manifest the harness recognizes "
        f"({manifests}), so there was nothing it could run or test. The files "
        "exist; the result is unverified, not failed."
    )
    if any(f.lower().endswith(_WEB_PAGE_SUFFIXES) for f in found):
        message += (
            " Standalone HTML/JavaScript pages aren't executed by the harness: "
            "open the page in a browser to check it, or add a package.json "
            "with a `test` script to make it verifiable."
        )
    return message


def run_full_verification(working_dir: str, runner: CommandRunner | None = None) -> VerificationRun:
    """The full pipeline: detect → set up (Python: the project environment)
    → discover plan → execute every check → aggregate. This is the
    language-neutral entry point `runner.py`'s post-hoc verification loop
    and `certo verify` call; the agent-facing `run_tests` tool above reuses
    stages 1-3 directly for non-Python/Node languages instead of duplicating
    detection (see `RunTestsExecutor.__call__`).

    `runner` decides where commands run: host subprocesses by default, or
    the Docker container (project_env.WorkspaceRunner). Detection and
    planning read files on the host either way (the workspace is
    bind-mounted).
    """
    runner = runner or LocalRunner()
    detection = detect_project(working_dir)
    python_env = None
    if detection.language == "python":
        python_env = prepare_python_env(detection.root, runner, stop_at=working_dir)
    plan = discover_verification_plan(detection, python_env=python_env, runner=runner)
    return VerificationRun(
        checks=[execute_check(spec, runner=runner) for spec in plan],
        notices=tuple(python_env.notices) if python_env else (),
    )


# What a run was judged against, built from its VerificationRun. Here, not
# in runner.py, so `certo verify` can print the limitations without the SDK.
@dataclass(frozen=True)
class CompletionContract:
    """A structured, harness-computed statement of what a task run was
    actually judged against — deliberately not another LLM call or a bigger
    prompt (see DECISIONS.md): the goal is a record attached to
    the result, not more instructions fed back into the agent.
    """

    goal: str
    acceptance_criteria: list[str]
    verification_checks: list[str]
    limitations: list[str]


def _build_completion_contract(
    task: str, run: VerificationRun | None, *, skipped: bool, aborted: bool
) -> CompletionContract:
    checks = run.commands if run is not None else []
    limitations: list[str] = []
    if aborted:
        limitations.append(
            "The agent's run did not reach a normal finish (stuck or errored "
            "state) before verification could run; its own completion claim, "
            "if any, was not verified."
        )
    if skipped:
        limitations.append(
            "Automated verification was skipped (CERTO_VERIFY_TESTS=never); "
            "completion was not independently checked."
        )
    if run is not None:
        limitations.extend(run.limitation_notes)
    if not aborted and not skipped and not checks:
        limitations.append(
            "No automated check could be run for this project, so completion "
            "is unverified (not failed) — see the verification note for what "
            "was found."
        )
    acceptance_criteria = ["The task described in the original request is implemented."]
    acceptance_criteria.extend(f"`{cmd}` completes successfully." for cmd in checks)
    return CompletionContract(
        goal=task,
        acceptance_criteria=acceptance_criteria,
        verification_checks=checks,
        limitations=limitations,
    )
