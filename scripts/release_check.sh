#!/usr/bin/env bash
# Install Certo the way users do and check it works outside the dev venv.
#
#   scripts/release_check.sh                 # build the wheel, then check it
#   scripts/release_check.sh --wheel PATH    # check an already-built wheel
#   scripts/release_check.sh --with-llm      # also run a real agent task
#
# The wheel is `uv tool install`ed into a throwaway UV_TOOL_DIR /
# UV_TOOL_BIN_DIR (never your real ones), and every command runs from an
# empty temp directory, so no repo file and no .env is picked up. Checks:
#
#   - `certo --help` works;
#   - `certo init --yes --no-check` in an empty directory writes the user
#     settings file under a throwaway XDG_CONFIG_HOME (mode 600) and the
#     sample folder with no .env in it, a second one is refused, and
#     `certo check` from an unrelated folder names the user file as the
#     source and reports the missing key without a traceback;
#     `certo init --yes --local` writes FOLDER/.env (mode 600) instead, and
#     `certo init` with no terminal and no flags writes every preset
#     commented out;
#   - `certo verify` on three fixture projects, with no LLM:
#       pass  - a Python project with passing tests      -> verified, exit 0
#       fail  - a Python project with a failing test     -> failed,   exit 1
#       dep   - tests import a package installed only in
#               the project's own .venv (not pytest)     -> verified, exit 0,
#               pytest installed into that .venv, and
#               nothing installed into Certo's own env;
#   - with --with-llm, the real smoke task against whatever CERTO_LLM_* variables
#     are exported, expecting `Verification: verified`.
#
# Needs uv and network access (to install the wheel's dependencies and the
# fixtures' packages). Run it directly, not through `uv run`.
set -euo pipefail

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }

wheel=""
with_llm=0
while [ $# -gt 0 ]; do
  case "$1" in
    --wheel) wheel="${2:?--wheel needs a path}"; shift 2 ;;
    --with-llm) with_llm=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

repo="$(cd "$(dirname "$0")/.." && pwd)"
# `cd && pwd` normalizes the path (e.g. a `//` from TMPDIR) to the form
# Certo prints, so its output can be matched against it.
work="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/certo-release-check.XXXXXX")" && pwd)"
trap 'rm -rf "$work"' EXIT
# Nothing from the caller's virtualenv should leak into the checks.
unset VIRTUAL_ENV CONDA_PREFIX || true
# Nor from their user settings file: Certo reads $XDG_CONFIG_HOME/certo/.env.
export XDG_CONFIG_HOME="$work/xdg"
user_env="$XDG_CONFIG_HOME/certo/.env"

failures=0
pass() { echo "  ok    $1"; }
fail() { echo "  FAIL  $1"; failures=$((failures + 1)); }

echo "== Wheel"
if [ -z "$wheel" ]; then
  uv build --wheel --out-dir "$work/dist" "$repo" >/dev/null
  wheel="$(ls "$work"/dist/certo-*.whl)"
fi
wheel="$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"
echo "  $wheel"

echo "== uv tool install (throwaway tool dir)"
export UV_TOOL_DIR="$work/tools"
export UV_TOOL_BIN_DIR="$work/bin"
uv tool install --quiet "$wheel"
certo="$UV_TOOL_BIN_DIR/certo"
tool_python="$UV_TOOL_DIR/certo/bin/python"
[ -x "$certo" ] && pass "installed $certo" || fail "certo was not installed"

# run NAME EXPECTED_EXIT EXPECTED_LINE CMD...: run from an empty directory,
# print the full output, and check the exit code and verdict line.
run() {
  local name="$1" want_exit="$2" want_line="$3"
  shift 3
  local cwd="$work/cwd-$name" out code=0
  mkdir -p "$cwd"
  out="$(cd "$cwd" && "$@" 2>&1)" || code=$?
  echo "--- $name: $* (exit $code)"
  echo "$out" | sed 's/^/    /'
  [ "$code" = "$want_exit" ] && pass "$name exit code $code" || fail "$name exit code $code, expected $want_exit"
  if [ -n "$want_line" ]; then
    echo "$out" | grep -qx "$want_line" && pass "$name: $want_line" || fail "$name: missing '$want_line'"
  fi
  last_output="$out"
}

echo "== certo --version"
wheel_version="$(basename "$wheel" | cut -d- -f2)"
run version 0 "certo $wheel_version" "$certo" --version

echo "== certo --help"
run help 0 "" "$certo" --help
echo "$last_output" | grep -qE "^  verify \[PATH\] " && pass "help lists certo verify" || fail "help doesn't list certo verify"

echo "$last_output" | grep -qE "^  init \[FOLDER\] " && pass "help lists certo init" || fail "help doesn't list certo init"

echo "== certo init"
# No provider key may leak in from the caller: --yes would use it.
noenv=(env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u CERTO_LLM_MODEL -u CERTO_LLM_API_KEY -u CERTO_LLM_BASE_URL)
# GNU stat first: on Linux `stat -f` means "file system status" and succeeds
# with the wrong output, while macOS stat rejects -c and falls back.
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
run init 0 "  certo tasks/wordle.md --project wordle" "${noenv[@]}" "$certo" init --yes --no-check </dev/null
[ -f "$user_env" ] && pass "init --yes wrote the user settings file" || fail "init --yes did not write $user_env"
[ "$(mode "$user_env")" = 600 ] && pass "the user file has mode 600" || fail "the user file has mode $(mode "$user_env"), expected 600"
grep -qx "CERTO_LLM_MODEL=openai/.*" "$user_env" && pass "the user file selects the OpenAI default" || fail "the user file has no active CERTO_LLM_MODEL"
ws="$work/cwd-init/certo-workspace"
for f in .gitignore README.md tasks/wordle.md tasks/hanoi.md tasks/space-rocks.md tasks/mazeman.md tasks/invaders.md; do
  [ -f "$ws/$f" ] && pass "init wrote $f" || fail "init did not write $f"
done
[ ! -e "$ws/.env" ] && pass "the sample folder has no .env" || fail "init --yes wrote $ws/.env"
grep -qx ".env" "$ws/.gitignore" && pass ".gitignore covers .env" || fail ".gitignore misses .env"
out="$(cd "$work/cwd-init" && "$certo" init --yes --no-check </dev/null 2>&1)" \
  && fail "a second init replaced the user file" || pass "a second init is refused: $out"
mkdir -p "$work/elsewhere"
out="$(cd "$work/elsewhere" && "${noenv[@]}" "$certo" check 2>&1)" && code=0 || code=$?
echo "$out" | sed 's/^/    /'
echo "$out" | grep -q "^  CERTO_LLM_MODEL .*from user settings ($user_env)" \
  && pass "certo check elsewhere names the user file as the source" || fail "certo check didn't name $user_env"
{ [ "$code" = 1 ] && echo "$out" | grep -q "CERTO_LLM_API_KEY is required" && ! echo "$out" | grep -q Traceback; } \
  && pass "certo check reports the missing key" || fail "certo check (exit $code) didn't report the missing key"
run init-local 0 "" "${noenv[@]}" "$certo" init --yes --local --no-check </dev/null
local_env="$work/cwd-init-local/certo-workspace/.env"
[ -f "$local_env" ] && [ "$(mode "$local_env")" = 600 ] \
  && pass "init --local wrote the folder's .env with mode 600" || fail "init --local: no $local_env with mode 600"
run init-notty 0 "" "${noenv[@]}" "$certo" init plain </dev/null
if grep -q "^CERTO_LLM_" "$work/cwd-init-notty/plain/.env"; then
  fail "init without a terminal set a value"
else
  pass "init without a terminal left every preset commented out"
fi

echo "== Fixtures"
fixtures="$work/fixtures"
mkdir -p "$fixtures/pass" "$fixtures/fail" "$fixtures/dep"

cat > "$fixtures/pass/hello.py" <<'PY'
def hello() -> str:
    return "hello"


if __name__ == "__main__":
    print(hello())
PY
cat > "$fixtures/pass/test_hello.py" <<'PY'
from hello import hello


def test_hello():
    assert hello() == "hello"
PY

cp "$fixtures/pass/hello.py" "$fixtures/fail/hello.py"
cat > "$fixtures/fail/test_hello.py" <<'PY'
from hello import hello


def test_hello():
    assert hello() == "goodbye"
PY

cat > "$fixtures/dep/pyproject.toml" <<'TOML'
[project]
name = "dep-fixture"
version = "0.0.0"
dependencies = ["tomli-w"]
TOML
cat > "$fixtures/dep/render.py" <<'PY'
import tomli_w


def render(data: dict) -> str:
    return tomli_w.dumps(data)
PY
cat > "$fixtures/dep/test_render.py" <<'PY'
from render import render


def test_render():
    assert render({"a": 1}) == "a = 1\n"
PY
# The dependency lives only in the project's own venv, without pytest.
uv venv --quiet "$fixtures/dep/.venv"
uv pip install --quiet --python "$fixtures/dep/.venv/bin/python" tomli-w
if "$tool_python" -c "import tomli_w" 2>/dev/null; then
  fail "tomli_w is importable from Certo's own environment; the dep fixture proves nothing"
fi

echo "== certo verify"
run verify-pass 0 "Verification: verified" "$certo" verify "$fixtures/pass"
run verify-fail 1 "Verification: failed" "$certo" verify "$fixtures/fail"
run verify-dep 0 "Verification: verified" "$certo" verify "$fixtures/dep"
echo "$last_output" | grep -q "Installed pytest into the project environment $fixtures/dep/.venv" \
  && pass "verify-dep: pytest installed into the project's venv" \
  || fail "verify-dep: no notice of pytest being installed into the project's venv"
"$fixtures/dep/.venv/bin/python" -c "import pytest" 2>/dev/null \
  && pass "pytest is in the project's venv" || fail "pytest is not in the project's venv"
if "$tool_python" -c "import pytest" 2>/dev/null; then
  fail "pytest is importable from Certo's own environment"
else
  pass "Certo's own environment still has no pytest"
fi

if [ "$with_llm" = 1 ]; then
  echo "== Live smoke task (--with-llm)"
  if [ -z "${CERTO_LLM_MODEL:-}" ]; then
    fail "--with-llm needs CERTO_LLM_MODEL (and CERTO_LLM_API_KEY or CERTO_LLM_BASE_URL) exported"
  else
    echo "  model: $CERTO_LLM_MODEL"
    export CERTO_PROJECTS_DIR="$work/projects"
    run smoke 0 "Verification: verified" \
      "$certo" "Create hello.py that prints hello, plus a pytest test for it" --project smoke
  fi
fi

echo
if [ "$failures" -gt 0 ]; then
  echo "release check FAILED ($failures problem(s))"
  exit 1
fi
echo "release check passed"
