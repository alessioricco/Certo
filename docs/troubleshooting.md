# Troubleshooting

Problems people actually hit, with their fix. Each entry starts with what
you see, then the cause in one sentence, then what to do. Search this page
for a few words of your error message.

For model problems, `certo check` is the fastest test: it shows where each
setting comes from and makes one small call to the model.

**Contents**

- Setup: [`certo init` runs an agent](#certo-init-runs-an-agent-instead-of-asking-questions),
  [externally managed environment](#externally-managed-environment-from-pip),
  [no matching distribution](#no-matching-distribution-found-for-certo-from-pip),
  [no model configured](#no-model-configured),
  [old `LLM_*` names](#certo_llm_model-is-required-although-llm_model-is-set),
  [settings from an unexpected place](#a-setting-comes-from-a-place-you-didnt-expect),
  [`# comment` read as a value](#certo_llm_base_url-is-read-as-a--comment)
- Model: [missing key](#missing-api-key), [wrong key](#wrong-api-key),
  [out of credit](#out-of-credit-or-rate-limited),
  [unknown model](#the-provider-doesnt-know-the-model),
  [no tool calling](#the-model-doesnt-support-tool-calling),
  [can't reach the provider](#cant-reach-the-provider),
  [cost unknown](#the-cost-shows-as-unknown)
- Ollama: [not running](#ollama-isnt-running), [another machine](#ollama-on-another-machine),
  [does not support thinking](#does-not-support-thinking),
  [context window below the minimum](#context-window-below-the-minimum),
  [agent behaves erratically](#the-agent-behaves-erratically-with-ollama),
  [very slow steps](#every-step-is-very-slow)
- Verdicts: [inconclusive, no tests](#inconclusive-the-project-has-no-tests),
  [inconclusive, unknown type or HTML page](#inconclusive-unknown-project-type-or-a-standalone-html-page),
  [inconclusive, several projects](#inconclusive-several-projects-in-one-folder),
  [missing toolchain](#a-toolchain-is-missing-node-go-rust-maven-or-gradle),
  [pytest unavailable](#pytest-is-unavailable),
  [`no_progress`](#no_progress), [`retry_exhausted`](#retry_exhausted),
  [`budget_exhausted`](#budget_exhausted),
  [nothing to resume](#nothing-to-resume),
  [Rust: `cargo clippy` unavailable](#rust-cargo-clippy-is-unavailable)
- Model files and escalation: [files not found](#no-models_listyaml-or-modelsyaml-found),
  [old format](#modelsyaml-is-in-the-old-format),
  [problems](#the-model-files-have-problems),
  [warnings](#warnings-about-the-model-files),
  [`--escalate` refuses to start](#--escalate-refuses-to-start),
  [stops after two `inconclusive` rungs](#escalation-stops-after-two-rungs-with-inconclusive),
  [stops before the last rung](#escalation-stops-before-the-last-rung),
  [`--models` failures](#certo-check---models-a-model-fails)
- Skills: [a skill doesn't fire](#a-skill-doesnt-fire),
  [can't load](#isnt-a-skill-certo-can-load),
  [already has a skill named](#already-has-a-skill-named),
  [a downloaded skill is off](#a-downloaded-skill-is-off),
  [a skill with a symlink](#upstream-skill-contains-a-symlink-that-leads-outside-it),
  [OpenHands plugins](#openhands-plugins-would-be-loaded-into-this-run),
  [replaces the official one](#your-skill-replaces-the-official-one),
  [an old skill setting is no longer read](#certo_skills_dir-is-no-longer-read)
- Benchmark: [no bench.yaml or model files](#certo-bench-no-benchyaml-or-model-files),
  [unknown model](#certo-bench-unknown-model),
  [`--parallel` refused](#certo-bench---parallel-is-refused),
  [nothing starts](#certo-bench-nothing-starts),
  [results folder refused](#certo-bench-the-results-folder-is-refused),
  [Node tasks show "hidden tests error"](#certo-bench-node-tasks-show-hidden-tests-error),
  [verified with no tests](#certo-bench-a-node-run-is-verified-but-fooled)
- Other: [uncommitted changes warning](#warning-uncommitted-changes),
  [an action outside the project root was blocked](#certo-blocked-an-action-outside-the-project-root),
  [wrong path or read-only file system](#the-agent-writes-to-the-wrong-path),
  [`init` refuses to write](#certo-init-says-a-file-already-exists),
  [Docker](#docker)

## Setup

### `certo init` runs an agent instead of asking questions

**You see:** `certo init` starts working on a task called "init".

**Cause:** your Certo is older than 0.1.4, which added `certo init`.

**Fix:** run `certo --version`, then upgrade: `uv tool upgrade certo` or
`pip install -U certo`.

### "No matching distribution found for certo" from pip

**You see:** `pip install -U certo` fails, and lists every version as
`Requires-Python >=3.12`:

```text
ERROR: Ignored the following versions that require a different python version: ... 0.2.1 Requires-Python >=3.12; 0.2.2 Requires-Python >=3.12
ERROR: Could not find a version that satisfies the requirement certo (from versions: none)
ERROR: No matching distribution found for certo
```

**Cause:** that `pip` belongs to a Python older than 3.12, often an old
system or Homebrew one that comes first on your `PATH`. `pip --version`
says which Python it uses.

**Fix:** if you installed Certo with uv, upgrade it with uv, which uses
its own Python: `uv tool install --upgrade certo`. Otherwise use the
`pip` of the virtual environment Certo is in
(`~/.venvs/certo/bin/pip install -U certo`), or make a new one with
Python 3.12 or newer, as in [Getting started](getting-started.md#1-install).

### "externally-managed-environment" from pip

**You see:** `pip install certo` fails with `error:
externally-managed-environment`.

**Cause:** your system Python doesn't allow installing packages into it.

**Fix:** install with `uv tool install certo`, or into a virtual
environment, as in [Getting started](getting-started.md#1-install).

### No model configured

**You see:**

```text
Configuration error: CERTO_LLM_MODEL is required (e.g. 'anthropic/claude-sonnet-5-5' or 'ollama/qwen3.8:27b'), and it isn't set in any of the three places Certo looks, in this order: 1. the environment (export CERTO_LLM_MODEL=...); 2. .env in the current folder (/home/me/project/.env); 3. the user settings file (/home/me/.config/certo/.env). Run certo init to write it, or set it in one of these. Switching provider = changing only this value.
```

**Cause:** `CERTO_LLM_MODEL` isn't set in your shell, in `.env` in this
folder, or in the user settings file, and you didn't pass `--model`.

**Fix:** run `certo init`. Or set it yourself in one of those places, as
in [OpenAI, Claude and Gemini](guides/openai-claude-gemini.md#set-up-by-hand).
Or pass `--model MODEL` for this run only (and `--api-key` or `--base-url`
as needed). If `init` saved the settings for "this folder only", run
`certo` from that folder, or run `certo init --global`.

### "CERTO_LLM_MODEL is required" although `LLM_MODEL` is set

**You see:** the error above, ending with `Found LLM_MODEL, which Certo no
longer reads`.

**Cause:** since 0.1.3, Certo only reads the `CERTO_LLM_` names, so that
other tools' `LLM_*` variables can't leak in.

**Fix:** rename `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` and
`LLM_REASONING_EFFORT` to `CERTO_LLM_MODEL` and so on.

### A setting comes from a place you didn't expect

**You see:** Certo uses a model or key you didn't set in this folder.

**Cause:** an exported variable, the folder's `.env` and the user settings
file are all read, and the first one that sets a value wins, for each
setting separately.

**Fix:** run `certo check`. It prints where each setting came from:
`environment variable`, `./.env (<path>)` or `user settings (<path>)`.
Change it there. (Before 0.1.4, LiteLLM could also load a `.env` of its
own; upgrade if you are on an older version.)

### `CERTO_LLM_BASE_URL` is read as a `# comment`

**You see:** Certo tries to reach an address like `# only for local
models`.

**Cause:** in a `.env` file, `python-dotenv` keeps a trailing comment as
the value when nothing else is on the line: `CERTO_LLM_BASE_URL=   # comment`.

**Fix:** leave the line as `CERTO_LLM_BASE_URL=` with nothing after it, or
delete it. Put comments on their own line.

## Model and provider

### Missing API key

**You see:**

```text
Configuration error: CERTO_LLM_API_KEY is required unless CERTO_LLM_BASE_URL is set (e.g. a local Ollama/vLLM/LM Studio endpoint that needs no key).
```

**Cause:** a cloud model needs a key, and none is set.

**Fix:** paste your key after `CERTO_LLM_API_KEY=` in the settings file
that `certo check` names, or export it. Then run `certo check`.

### Wrong API key

**You see**, from `certo check`:

```text
Checking the model openai/gpt-6.1-sol... OpenAI rejected the API key. Check CERTO_LLM_API_KEY in your settings: it must be a valid key for OpenAI, pasted with no spaces.
```

**Cause:** the key is wrong, expired, or belongs to another provider than
the one in `CERTO_LLM_MODEL`.

**Fix:** copy the key again from the provider's site, with no spaces or
quotes around it. Make sure it matches the provider before the `/` in
`CERTO_LLM_MODEL`. The message says `.env`, but the key may be in your user
settings file or your shell: `certo check` shows which.

### Out of credit, or rate limited

**You see**, from `certo check`:

```text
Anthropic refused the request: the account is out of credit, or it is being rate limited. Check your billing page, or wait a minute, then run certo check again.
```

During a task, the run stops with `Error:` and the provider's message
(for example about quota, billing or rate limits).

**Cause:** the provider refuses calls because the account has no credit,
or because too many calls were made too quickly.

**Fix:** add credit on the provider's billing page, or wait a minute and
try again. With [automatic model selection](guides/pick-models-automatically.md),
Certo falls back to the next model on its own.

### The provider doesn't know the model

**You see:** `... doesn't know the model ... Check the spelling of
CERTO_LLM_MODEL`, or for Ollama, `Ollama has no model named ...`.

**Cause:** the model id is misspelled, retired, or your key has no access
to it; for Ollama, the model isn't pulled.

**Fix:** check the id against the provider's model list. For Ollama, run
`ollama list`, and `ollama pull <model>` if needed.

### The model doesn't support tool calling

**You see**, from `certo check`:

```text
The model ... doesn't support tool calling, which Certo's agent needs. Choose another model in CERTO_LLM_MODEL in your settings.
```

or `... answered, but without calling a tool.`

**Cause:** Certo's agent works only through tool calls (running commands,
editing files), and this model can't make them, or didn't.

**Fix:** choose a model with tool (function) calling support. For Ollama,
`qwen3.8:27b`, the model `certo init` suggests, supports it.

### Can't reach the provider

**You see:** `Couldn't reach OpenAI. Check your internet connection; if it
works, the provider may be having an outage, so try again in a few
minutes.`

**Cause:** no network, a proxy or firewall, or a provider outage.

**Fix:** check your connection, then try again later.

### The cost shows as unknown

**You see:** `Total cost: $0.0000 + unknown (no pricing data for ...)`.

**Cause:** LiteLLM, installed with Certo, has no price for this model.
It is newer than your LiteLLM, or a local model whose id doesn't start
with a local provider (`ollama/`, `ollama_chat/`, `lm_studio/`,
`hosted_vllm/`, `llamafile/`), for example an `openai/` model on a local
server. A model with one of those prefixes is counted as free.

**Fix:** for a cloud model, upgrade (`uv tool upgrade certo`, or
`pip install -U litellm`). For a local model under another prefix this is
normal. The tokens are still counted.

## Ollama

### Ollama isn't running

**You see:**

```text
Checking the model ollama/qwen3.8:27b (a local model may take a minute to load)... Couldn't reach the server at http://localhost:11434. Check CERTO_LLM_BASE_URL in your settings and that the server is running. If Ollama runs on another machine, start it there with OLLAMA_HOST=0.0.0.0.
```

**Cause:** Ollama isn't started, or listens on another address.

**Fix:** start Ollama (`ollama serve`, or open the app), then run
`certo check` again.

### Ollama on another machine

**You see:** the same `Couldn't reach the server at http://<address>:11434`
message.

**Cause:** by default Ollama only accepts connections from its own
machine.

**Fix:** on the Ollama machine, start it with `OLLAMA_HOST=0.0.0.0 ollama
serve`. On the Certo machine, set
`CERTO_LLM_BASE_URL=http://<that machine's address>:11434`. Check that no
firewall blocks port 11434. See
[Ollama and local models](guides/ollama-and-local-models.md#use-ollama-on-another-machine).

### "does not support thinking"

**You see:** `OllamaException: "qwen3-coder:30b" does not support thinking`
on the first call.

**Cause:** Certo asked the model to think (reason), and this model has no
thinking mode.

**Fix:** clear `CERTO_LLM_REASONING_EFFORT` (and `--reasoning-effort`, or
`reasoning_effort` in the model files), or set it to `none`. When it is
empty, Certo sends no reasoning setting to Ollama models. Versions up to
0.1.0 always asked for thinking; upgrade if you are on one.

### Context window below the minimum

**You see:** `context window of 8,192 tokens, which is below the minimum
of 16,384`, or, for an Ollama model, `ollama/qwen3.8:27b has a context
window of 4,096 tokens (the Ollama server's setting), below the 16,384 an
agent needs`, before any work starts. `certo-admin check-llm` reports it
as a `setup` failure.

**Cause:** the model's context window is under 16,384 tokens: as LiteLLM
reports it, as the Ollama server gave it to the model, or as
`CERTO_LLM_CONTEXT_TOKENS` sets it. Ollama's default on smaller machines
is 4,096.

**Fix:** for Ollama, set `CERTO_LLM_CONTEXT_TOKENS=32768` (Certo asks the
server for it), or start Ollama with `OLLAMA_CONTEXT_LENGTH=32768`.
Otherwise choose a model with a larger window, such as a coder model.
Common with older models such as `ollama/llama3`.

### A warning about a small context window

**You see:** `has a context window of 24,576 tokens (the Ollama server's
setting), under CERTO_CONTEXT_WARN_TOKENS=32,768` when a run starts.

**Cause:** the model's window is smaller than `CERTO_CONTEXT_WARN_TOKENS`
(32,768 by default). The run goes on; a long task fills the window
sooner, and its older steps are then summarized.

**Fix:** follow the message: for Ollama, set
`CERTO_LLM_CONTEXT_TOKENS=32768` or start Ollama with
`OLLAMA_CONTEXT_LENGTH=32768`. If the smaller window is what you want,
lower `CERTO_CONTEXT_WARN_TOKENS`, or set it to `0`.

### The agent behaves erratically with Ollama

**You see:** the agent repeats steps, forgets the task, wanders off, or
stops with half the work done, although `certo check` passes.

**Cause:** Ollama's default context window is small (4096 tokens on
machines with less than 24 GB of GPU memory), so the model can't see the
start of the task any more.

**Fix:** start Ollama with a larger window, for example
`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or raise it in the Ollama
app's settings. `ollama ps` shows the context a loaded model got.

### The run ends at once, with a tool call as the agent's last message

**You see:** with a local model, the agent's answer is a tool call
written as text, such as `{"command": "view", "path": "..."}`, and
Certo prints:

```
Certo: the agent wrote a tool call as text instead of making it, so nothing ran. Asking it to make the call (1 of 3 in a row).
```

When the model keeps doing it without making a real call in between,
the run ends after the last reminder, often within a minute, with
`inconclusive` or `unchanged`.

**Cause:** the model wrote its tool call as plain text instead of making
a real tool call, so the agent framework took it as the final answer.
It depends on the model: in Certo's saved benchmark runs,
`qwen3.6:35b-a3b` did it in 28 of 28 runs, `devstral-small-2:24b` in 18
of 27 and `qwen3.8:27b` in about 1 run in 7, also with a 32,768-token
context window; `gemma4:31b-it-qat`, `qwen3-coder:30b` and the cloud
models never did.

**Fix:** Certo sends the call back to the agent, up to
`CERTO_TOOL_CALL_REMINDERS` times in a row (default 3, see
[Configuration](reference/configuration.md#limits-and-verification)).
When the agent makes a real call after a reminder, the count starts
again, so a model that slips now and then keeps going.
In Certo's [reminder benchmark](benchmark/reminders-0.1.26.md),
`qwen3.8` made one real call after most reminders, then went back to
writing calls as text, so no run was saved. If runs still end this way,
raise the context window (see
[The agent behaves erratically with Ollama](#the-agent-behaves-erratically-with-ollama)),
update Ollama, and run `certo check`, which fails when the answer isn't a
real tool call. If it keeps happening, use another model.

### The run ends on a sentence of plans

**You see:** with a local model, the agent's last message says what it
will do next, such as `Now let me add the save and load methods.`
(sometimes written as `{"type": "text", "text": "..."}`), and nothing
after it. Certo prints:

```
Certo: the agent said what it would do next but made no tool call, so nothing ran. Asking it to make the call (1 of 3 in a row).
```

**Cause:** the model ended its turn with a plan instead of the tool call
that carries it out, so the agent framework took it as the final answer.
In Certo's saved benchmark runs it happened 4 times, all on local
models, and never on a cloud model.

**Fix:** Certo tells the agent to make the call, or to say the task is
done, sharing the limit of the reminders above
(`CERTO_TOOL_CALL_REMINDERS`, `0` turns both off).

### Every step is very slow

**You see:** each step of the agent takes minutes, and tasks end with
`budget_exhausted`.

**Cause:** the model is larger than your GPU or unified memory, so Ollama
runs part of it on the CPU.

**Fix:** check `ollama ps` while the model is loaded. If the `PROCESSOR`
column shows a CPU share, use a smaller model (for example
`qwen2.5-coder:7b` instead of `qwen3.8:27b`) or a smaller quantization.

If one answer takes longer than `CERTO_LLM_TIMEOUT_SECONDS` (300 seconds
by default; `certo init` writes 1200 for Ollama), the call to the model
fails and starts over, so the step may never finish. The log shows
`litellm.Timeout: ... timed out after 300.0 seconds`. Raise
`CERTO_LLM_TIMEOUT_SECONDS` (or `timeout_seconds` in the model files), for
example to `1200`. A model that thinks at length can need that even when
it runs fully on the GPU. See [Ollama and local models](guides/ollama-and-local-models.md#slow-answers-and-the-call-timeout).

## Verdicts

What to do after any verdict, step by step, is in
[What to do after each verdict](guides/after-the-verdict.md). This section
covers the messages.

### `inconclusive`: the project has no tests

**You see:** `Verification: inconclusive`, with no explanation, or the
note `pytest: no tests collected`.

**Cause:** there was nothing to run: no test files, or pytest found zero
tests. Certo never counts that as a pass.

**Fix:** ask for tests in the task ("..., with pytest tests"), or add them.
To make this case fail in scripts, use `--require-verification`.

### `inconclusive`: unknown project type, or a standalone HTML page

**You see:**

```text
Verification: inconclusive
  - verification: Found index.html — but no project manifest the harness recognizes (pyproject.toml, package.json, go.mod, Cargo.toml, pom.xml, build.gradle), so there was nothing it could run or test. The files exist; the result is unverified, not failed. Standalone HTML/JavaScript pages aren't executed by the harness: open the page in a browser to check it, or add a package.json with a `test` script to make it verifiable.
```

**Cause:** Certo didn't recognise the project type, so it had no command
to run. The files exist; they just weren't checked.

**Fix:** for a web page, open it in a browser, or ask for a
`package.json` with a `test` (or `build`) script. For other languages, see
[Verification by language](reference/verification-by-language.md#not-covered).

### `inconclusive`: several projects in one folder

**You see:** a note starting `Multiple candidate projects were found with
no single obvious root`, listing the candidates.

**Cause:** the folder holds several projects side by side, and none at
the top, so Certo can't tell which one to check.

**Fix:** run Certo from (or `certo verify`) the sub-project folder you
mean. In a Certo workspace (a folder with `projects/`) a new task gets its
own project folder, so this happens only in other folders.

### A toolchain is missing (Node, Go, Rust, Maven or Gradle)

**You see:** `Verification: inconclusive`, with a note such as
`npm run build: npm not found on PATH`,
`go test: go is configured (go.mod present) but not installed`,
`cargo test: cargo is configured (Cargo.toml present) but not installed`,
or `mvn test: pom.xml is present but neither ./mvnw nor mvn is available`.

**Cause:** Certo runs the project's own tools and doesn't install them.

**Fix:** install the toolchain (Node 18+ with npm, Go, Rust with cargo, or
Maven or Gradle), check it works in the same terminal (`npm --version`,
`go version`, ...), and run again. A Maven or Gradle wrapper (`./mvnw`,
`./gradlew`) in the project also works. In Docker mode, the tool must be in
the image.

### pytest is unavailable

**You see:** `pytest: pytest is not installed in the project environment
(...) and installing it failed: ...`, or `... could not be run`.

**Cause:** Certo couldn't install pytest into the project's environment
(often no network), or the project's own `.venv` is broken.

**Fix:** check your network, or install pytest into the project's
environment yourself. Certo never repairs a `.venv` it didn't create:
delete or fix a broken one, and Certo will create a new one.

### `no_progress`

**You see:**

```text
Certo verification: the fix attempt just made produced no observable change — the same check (pytest failed (exit 1)) is still failing with identical output (ignoring timing). Stopping early rather than spending the rest of the retry budget on attempts that already provably didn't help — this project needs manual attention.

Verification: no_progress
```

**Cause:** the agent's fix attempt changed nothing in the failing check's
output, so more attempts were unlikely to help.

**Fix:** look at the failure yourself; it is in the project. Useful
questions:

- Is the **test** wrong rather than the code? Agents sometimes chase a
  test that expects the wrong thing.
- Is the failure about the environment (a missing package, a network
  call) rather than the code?
- Is the task too hard for this model? Try a stronger model with
  `--model`.

Then fix it by hand, or resume with a precise instruction, for example
`certo --resume "test_board.py::test_invalid_move expects a move that is
legal. Fix the test, not the code."`: the agent keeps everything it already
tried (see [Resume an interrupted run](guides/resume-a-run.md)).
`certo verify` checks the result for free.

### `retry_exhausted`

**You see:** `Certo verification: the project's checks are still failing
after 2 automated fix attempt(s) (...). Giving up — this project needs
manual attention.`

**Cause:** the agent kept trying different fixes, and the checks still
failed after the allowed attempts.

**Fix:** read the failure (`certo verify` prints it in full, and
`.certo/STATUS.md` keeps its end), then fix by hand, or continue with
`certo --resume`, adding an instruction or a stronger `--model`.
`CERTO_MAX_VERIFY_RETRIES` allows more attempts, at more cost.

### `budget_exhausted`

**You see:** `Verification: budget_exhausted`.

**Cause:** the whole task took longer than `CERTO_MAX_TASK_SECONDS` (30
minutes by default). Certo stops the agent after the step it is on. On
local runs a call to the model can't wait longer than the time left, and
isn't tried again once the budget is gone; a terminal command can't ask
for a longer timeout than the time left (the agent is told to use a
shorter one). When the
agent's last run ends after the budget, Certo still runs the project's
checks once: if they pass, the verdict is `verified`, not this one. So
`budget_exhausted` means the checks failed or couldn't run, or the time
ran out before a fix attempt; the check results are shown above the
verdict.

**Fix:** if the checks failed, there was no time left to fix them. If the
model is slow, see [very slow steps](#every-step-is-very-slow).
Otherwise split the task into smaller ones, or raise
`CERTO_MAX_TASK_SECONDS`. The work done so far stays in the folder, and
`certo --resume` continues it with a fresh time budget.

### Nothing to resume

**You see:** `Error: nothing to resume in /path: Certo keeps the last run's
state in .certo/, and there is none here (or it can't be read).`

**Cause:** `certo --resume` ran in a folder without a `.certo/` state: a
different folder or `--project` name than the task used, a run made with
`CERTO_SAVE_STATE=0`, or a deleted `.certo/` folder.

**Fix:** run it where the task ran (or with the same `--project`). If the
state is gone, start a new task; the files the agent wrote are still
there.

### Rust: `cargo clippy` is unavailable

**You see:**

```text
  passed      cargo test  (/usr/local/bin/cargo test)
  passed      cargo check  (/usr/local/bin/cargo check)
  unavailable cargo clippy  (/usr/local/bin/cargo clippy)

Verification: verified
  - cargo clippy: clippy is not installed (with rustup: rustup component add clippy)
```

**Cause:** Certo runs `cargo clippy` for every Rust project, and clippy
isn't installed. The verdict still comes from `cargo test`; the lint
check is just missing. Before 0.1.19, this made the project `failed`.

**Fix:** install the component: `rustup component add clippy`.

## Model files and escalation

### No `models_list.yaml` or `models.yaml` found

**You see:** `No models_list.yaml found: Certo looked in the current folder
and in ~/.config/certo. Run certo init models to set up your models and
write it. Or copy the example Certo ships and edit it:` followed by a `cp`
command (the same for `models.yaml`).

**Cause:** `--auto-model`, `--escalate`, `certo bench` and
`certo check --models` need both model files, and Certo ships them only as
examples, which it never reads. (`task_profiles.yaml` and
`escalation.yaml` are optional: a missing one is never this error.)

**Fix:** run `certo init models`: it offers the models you can reach,
tests them and writes the files. Or run the `cp` command the message
prints, then edit the copy: name the models you use in `models.yaml`,
with their keys. Put the files in a
project folder instead to use them for that project only. See
[The model files](reference/models-yaml.md).

### `models.yaml` is in the old format

**You see:** `models.yaml gives a model id for '...'` (or `has
task_profiles` / `has escalation`) `. Since version 0.1.10, models.yaml
holds only your personal settings: ...`

**Cause:** before 0.1.10, everything was in `models.yaml`. Now model ids,
descriptions and ratings go in `models_list.yaml`, task profiles in
`task_profiles.yaml`, and ladders in `escalation.yaml`.

**Fix:** copy the shipped `models_list.yaml.example` (or move your own
models into a `models_list.yaml`), and keep in `models.yaml` only `name`,
`api_key`, `base_url`, `activated` and any overrides for each model you
use. Move `task_profiles:` and `escalation:` into their own files.

### The model files have problems

**You see:** `Configuration error: .../models_list.yaml and
.../models.yaml have 2 problem(s):` followed by one line per problem, or
`Error: ...` lines in `certo check`.

**Cause:** every command that reads the model files checks them the same
way, and stops on an error. The errors and their fixes:

| Message starts with | Fix |
|---|---|
| `model '...' has api_key` (or `base_url`, `activated`) `. Those are personal settings` | Move those fields from `models_list.yaml` to the model's entry in `models.yaml`. |
| `models.yaml names '...', which isn't in models_list.yaml` | Fix the spelling, or add the model to `models_list.yaml` first. |
| `models.yaml lists '...' twice` | Keep one entry per model. |
| `Two models in models_list.yaml are named '...'` | Give each model a unique `name`. |
| `No model is enabled` | List the models you want in `models.yaml`, by name, without `activated: false`. |
| `Ladder '...', rung N: there is no model named '...'. Models: ...` | Fix the spelling: the message lists the names that exist. |
| `Ladder '...' lists ... twice with the same settings` | Remove the repeated rung (the same model with a different `reasoning_effort` is allowed). |
| `Ladder '...', rung N (...): retries must be 0 or more` | Use 0 or a positive number. |
| `escalation.cost_axis is '...', but no model has a rating with that name` | Set `cost_axis` to the rating you use for cost-effectiveness, usually `cost`. |
| `Ladder '...' has no usable rung` | Enable at least one of its models in `models.yaml`, or fix the names. |
| `Task profile '...': there is no model named '...'` | The profile's `model:` names a model that isn't in `models_list.yaml`. Fix the spelling, or remove `model:`. |
| `.../models_list.yaml has the 'task_profiles:' section. Since 0.1.20 it belongs in its own file` (or `'escalation:'`) | Your `models_list.yaml` is from before 0.1.20. Cut the section, with its key, into `task_profiles.yaml` (or `escalation.yaml`) next to it, or delete it if that file already has it. Nothing inside changes. See [Moving from one file](reference/models-yaml.md#moving-from-one-file-0119-and-earlier). |
| `... may only contain 'task_profiles:'` (or `'escalation:'`) | `task_profiles.yaml` and `escalation.yaml` each hold one section. Move anything else to `models_list.yaml` or `models.yaml`. |
| `CERTO_TASK_PROFILES_FILE names ..., which doesn't exist` (or `CERTO_ESCALATION_FILE`) | Fix the path, or clear the setting to let Certo look for the file. |
| `models.yaml: '...' has api_key ${NAME}, which isn't set in your settings file or the environment` (a warning; the model is left out) | Add `NAME=...` with the key to your settings file (`~/.config/certo/.env`, or `.env` in the project folder), or export it. Check the spelling of the variable in `models.yaml`. |

**Fix:** run `certo check` after each change: it lists every problem at
once.

### Warnings about the model files

**You see:** `Warning (models.yaml): ...` (or `Warning: ...` in
`certo check`). The command still runs.

| Warning | What it means |
|---|---|
| `... isn't in models.yaml, so this rung is skipped` | The ladder names a model you haven't enabled. Add it to `models.yaml`, or remove the rung. |
| `... has 'activated: false', so this rung is skipped` | The ladder names a model you turned off. Activate it, or remove the rung. |
| `... has only one usable rung (...), so it can't escalate` | Only one model in the ladder can be used. Enable another. |
| `Model '...' has no rating for ..., which task profile(s) ... weigh: it counts as 0` | Add the missing ratings, or the model ranks lower than it should. |
| `Model '...' has no api_key and no base_url` | It works only if the provider's own key variable (such as `OPENAI_API_KEY`) is set. Add `api_key` in `models.yaml` otherwise. |
| `... (capability ...) comes after ... but is rated less capable` | Your explicit ladder climbs to a weaker model. Allowed, if that's what you meant. |
| `Task profile '...': ... isn't enabled in models.yaml` | The profile's `model:` can't run, so the weights pick the model. Enable it, or remove `model:`. |

### `--escalate` refuses to start

| You see | Fix |
|---|---|
| `No models_list.yaml found` / `No models.yaml found` | See [No `models_list.yaml` or `models.yaml` found](#no-models_listyaml-or-modelsyaml-found). |
| `There is no escalation ladder named '...' in escalation.yaml. Ladders: ...` | Use one of the listed names, or leave the name out for the `default` (or derived) ladder. |
| `--escalate can't be combined with --auto-model or --model` (or `with --model`) | The ladder decides which models run. Drop the other flag. |
| `--model can't be used while CERTO_MODEL_SELECTION=escalate` | Drop `--model`, or set `CERTO_MODEL_SELECTION=manual` for this run. |
| `--resume can't be combined with escalation` | Resume without `--escalate`: it continues the last model's conversation. |

### Escalation stops after two rungs with `inconclusive`

**You see:** `Certo: ... ended inconclusive too, after ...: two models in a
row left nothing Certo could check, so escalation stops.`

**Cause:** neither model left anything Certo could run: no test ran, or no
check could run (no tests or build in the project, or a missing tool such
as `npm`). A third model would most likely face the same blank, so Certo
stops instead of paying for it.

**Fix:** ask for tests in the task ("... with pytest tests"), or add them
first. If a tool is missing, install it. See [`inconclusive`: the project has no tests](#inconclusive-the-project-has-no-tests).

### Escalation stops before the last rung

**You see:** `Certo: ... escalation stops: the cost so far, $..., has
reached CERTO_MAX_TASK_COST=...` or `... the task's time budget
(CERTO_MAX_TASK_SECONDS=...) is spent`.

**Cause:** a limit you set was reached. The verdict is the last rung's.

**Fix:** raise `CERTO_MAX_TASK_COST` or `CERTO_MAX_TASK_SECONDS`, or give
the cheaper rungs fewer fix attempts (`retries` in the ladder) so they hand
over sooner. Models with no known price count as 0 toward the cost cap.

### The run stops with `cost_exhausted`

**You see:** `Certo: the task has cost $..., reaching its limit
(CERTO_MAX_TASK_COST=...). The agent was stopped.`, then the verdict
`cost_exhausted`.

**Cause:** the task reached the cost limit you set, and its work didn't
pass the checks. The total can be a little over the limit: the model calls
made since Certo last read the cost are paid for.

**Fix:** `certo --resume` continues with a fresh limit. Or raise
`CERTO_MAX_TASK_COST`, split the task, or use a cheaper model. See
[`cost_exhausted`](guides/after-the-verdict.md#cost_exhausted).

**You see:** `Certo: ... changed no file either, after ...: two models in
a row did no work on this task, so escalation stops.`

**Cause:** two models in a row changed no file (each ended `unchanged`, or
`inconclusive` with no file written). Certo takes that as a sign the task
needs no change, rather than sending it to the most expensive model.

**Fix:** if the task does need a change, say exactly what in the task, or
resume with a stronger model: `certo --resume --model MODEL`. If both
models ended within a minute, check for
[tool calls written as text](#the-run-ends-at-once-with-a-tool-call-as-the-agents-last-message).

### `certo check --models`: a model fails

**You see:** a line such as `gpt-luna (openai/gpt-5.6-luna)... OpenAI
rejected the API key. Check its api_key in models.yaml: ...`.

**Fix:** follow the line: it names the field to fix, in `models.yaml` (the
key or address) or `models_list.yaml` (the model id). `--models` without
the model files fails with `--models: No models.yaml found` and the command
to copy the example.

## Skills

### A skill doesn't fire

**You see:** the agent ignores a skill you added, and
`certo skills list --task "..."` doesn't list it under "From its first
message".

**Cause:** trigger words match whole words only: `game` doesn't match
"games", and `test` doesn't match "tests". Or the skill is in another
project's folder, or (a `paths:` skill) the agent never touched a
matching file.

**Fix:** run `certo skills list --project NAME --task "your task"` (use
`--project .` for the current folder). Add the forms the task really uses
to `triggers:`, then add the skill again with `--yes`. See
[Write a good skill](guides/manage-skills.md#write-a-good-skill).

### "isn't a skill Certo can load"

**You see:**

```text
Error: broken.md isn't a skill Certo can load: while parsing a flow sequence
  in "<unicode string>", line 3, column 11
did not find expected ',' or ']'
```

**Cause:** the header between the `---` lines isn't valid YAML (here, a
`[` without its `]`). Nothing was copied. A skill already in a folder with
a broken header is listed as `can't load` and skipped by runs.

**Fix:** correct the header at the line the message names, then add the
skill again.

### "already has a skill named"

**You see:** `Error: ~/.config/certo/skills already has a skill named
'my-style'. Add --yes to replace it.`

**Cause:** that folder has a skill with the same `name`, and there was no
terminal to ask you.

**Fix:** add `--yes` to replace it, or give the new skill another `name`.

### A downloaded skill is off

**You see:** in `certo skills list`, `off (downloaded; turn it on with:
certo skills enable NAME --global)`, or `off (its files are modified; run:
certo skills sync --global)`.

**Cause:** a skill from git stays off until you enable it, and is turned
off again when its files no longer match the hash recorded when it was
downloaded (edited by hand, or deleted).

**Fix:** read its files, then run the command shown. To change a
downloaded skill, copy it, edit the copy, and add the copy as your own
skill.

### "Upstream skill contains a symlink that leads outside it"

**You see:** `Error: Upstream skill contains a symlink that leads outside
it (NAME); refusing to install.` from `certo skills add`.

**Cause:** the skill's folder contains a link to a file or folder outside
the skill. Certo copies only regular files, and never follows a link out
of the skill. (A link that stays inside the folder is fine: it is skipped,
and Certo names it.)

**Fix:** copy the files the skill needs into a folder of your own and add
it as your own skill
([Add a skill you wrote](guides/manage-skills.md#add-a-skill-you-wrote)).

### Your skill replaces the official one

**You see:** `Certo: your global skill 'pytest-conventions' replaces the
official one.` before a run.

**Cause:** one of your skills has the same `name` as an official skill.
The later one wins, so yours is used.

**Fix:** nothing, if you meant it. Otherwise rename your skill, or remove
it with `certo skills remove NAME --global` (or `--project NAME`).

### `CERTO_SKILLS_DIR is no longer read`

**You see:** `CERTO_SKILLS_DIR is no longer read: Certo no longer uses the
old skill folders.` (or the same for `CERTO_THIRD_PARTY_SKILLS_DIR` or
`CERTO_THIRD_PARTY_SKILLS_LOCK`).

**Cause:** your settings still name an old skill folder. Since 0.1.23,
Certo doesn't read `./skills` or `./third_party_skills/`, so a run no
longer gets the skills in them.

**Fix:** add each skill again with `certo skills add PATH --global` (or
`--project NAME`), then delete the line from your settings. See
[Moving from the old folders](guides/manage-skills.md#moving-from-the-old-folders).

### "OpenHands plugins would be loaded into this run"

**You see:** `Error: OpenHands plugins would be loaded into this run, and
Certo doesn't use them`, then a list of plugins with their folders. The
run, or `certo bench`, doesn't start.

**Cause:** OpenHands, the agent toolkit under Certo, loads plugins from
your user folders (`~/.agents/plugins/`, `~/.openhands/plugins/`) and,
for a project Certo generates, from a git repository around it. A plugin
can add skills, tools and hooks that Certo hasn't checked, so Certo
refuses to start instead.

**Fix:** move or rename each folder in the list while you use Certo (for
example `mv ~/.agents/plugins ~/.agents/plugins.off`). To keep a skill a
plugin offers, add it to Certo with `certo skills add`. For a generated
project, you can also set `CERTO_PROJECTS_DIR` to a folder outside the
repository. See [OpenHands plugins](guides/manage-skills.md#openhands-plugins).

## Benchmark (`certo bench`)

### `certo bench`: no bench.yaml or model files

**You see:**

```text
Configuration error: benchmark file not found: bench.yaml. Certo ships an example to start from; copy it and name the models to compare:
  cp /path/to/certo/examples/bench.yaml.example bench.yaml
```

The path in the `cp` line is where Certo is installed on your machine.

or `the benchmark takes its models, by name, from models.yaml and
models_list.yaml. No models.yaml found: ...` with the `cp` command for the
example.

**Cause:** the benchmark reads its models from the two model files, by
name, and what to compare from `bench.yaml`. It never uses `.env`.

**Fix:** run the `cp` command the message prints, and the ones for the
model file examples, then enable the models to compare in
`models.yaml`. Use `--config` for another benchmark file, or
`models_file` / `models_list_file` in it for other model files. See
[Benchmark models and strategies](guides/benchmark.md).

### `certo bench`: a model that isn't enabled

**You see:** `arm 'a': model 'x' has 'activated: false' in models.yaml,
and Certo never uses an inactive model.` or `model 'x' is in
models_list.yaml but not in models.yaml.`

**Cause:** an arm can only use a model that `models.yaml` enables. (Before
version 0.1.9 the benchmark ignored `activated`.)

**Fix:** list the model in `models.yaml` with its key or address, without
`activated: false`.

### `certo bench`: an escalate arm is refused

**You see:** `'models' must list at least two models` or `'models' lists a
model twice`.

**Fix:** list two or more different models in the order to climb, or
leave `models` out for the ladder derived from the ratings.

### `certo bench`: unknown model

**You see:**

```text
Configuration error: bench.yaml: arm 'sonnet': unknown model 'sonet'. The models file has: qwen-local, sonnet.
```

**Cause:** an arm's `model` must be the `name` of an entry in
`models.yaml`, not a LiteLLM model id.

**Fix:** use one of the names the message lists.

### `certo bench`: `--parallel` is refused

**You see:**

```text
Configuration error: --parallel needs cloud models only; qwen-local runs locally, and a local server serves one model at a time. Run without --parallel.
```

**Cause:** one arm uses a model served on your machine or network, which
can serve only one run at a time.

**Fix:** run without `--parallel`, or put the cloud arms in a benchmark
file of their own and run that one in parallel.

### `certo bench`: nothing starts

**You see:** the plan, then `Not a terminal, so nothing was started: add
--yes to run the benchmark.`

**Cause:** the benchmark can cost money, so it asks before starting, and
without a terminal it can't ask.

**Fix:** read the plan and its cost estimate, then run again with `--yes`.
Add `--max-cost` to cap the spending.

### `certo bench`: the results folder is refused

**You see:** `out already has benchmark results. Add --resume to continue
them, or choose another --out folder.`, or `--resume: out was made with
different tasks, arms, repeats or models.`

**Cause:** a results folder holds one benchmark. Certo won't mix runs of
two different benchmarks in it.

**Fix:** to continue the same benchmark, use `--resume` with the original
`bench.yaml`. To run a changed one, choose a new `--out` folder (or leave
`--out` out for a new dated folder).

### `certo bench`: Node tasks show "hidden tests error"

**You see:** progress lines like `...; hidden tests error; ...` for
`slugify`, `token-bucket` or `semver-order`, and `node is not installed`
in the run's JSON.

**Cause:** the Node tasks are graded with `node --test`, and Node isn't
installed.

**Fix:** install Node 18 or newer, or leave the Node tasks out with a
`tasks:` list in `bench.yaml`.

### `certo bench`: a Node run is verified but fooled

**You see:** a run with verdict `verified` and failed hidden tests, often
on a Node task where the agent wrote no tests.

**Cause:** before 0.1.25, `node --test` exiting successfully with no
test files counted as a pass. Now a run of no tests is `inconclusive`
(see [Verification by language](reference/verification-by-language.md#node-in-detail)),
so a fooled Node run means the agent's own tests passed but missed what
the hidden tests check.

**Fix:** nothing to fix in the benchmark: counting these runs is what
"fooled" is for.

### `certo bench`: a traceback after the results

**You see:** after the `Results:` line, a red traceback that ends with
`OSError: [Errno 9] Bad file descriptor`, from
`subprocess_terminal.py` (`PTY reader thread error`).

**Cause:** a terminal used by the agent was closed while the agent
framework was still reading from it, as the benchmark shut down.

**Fix:** none needed. The benchmark finished: the results are complete,
and the `runs recorded` count at the top of `results.md` says how many
runs were saved. Since 0.1.19, Certo hides this message; it appears only
with older versions.

## Other problems

### Certo blocked an action outside the project root

**You see:**

```text
Certo blocked an action outside the project root: /home/me/certo-workspace/projects/other is outside the project root /home/me/certo-workspace/projects/app. Work only inside the project root: nothing outside it is part of the task.
```

**Cause:** the agent tried to read, list, search or edit something above
or beside its project folder: a parent folder, another project, your home
folder. Certo stopped that one action and told the agent why; the run goes
on.

**Fix:** nothing, when the task doesn't need those files. When it does
(a shared library in `../shared`, say), run Certo from the folder that
holds everything the task needs, so that folder is the project root.

### Warning: uncommitted changes

**You see**, before the task starts:

```text
Warning: /home/me/code/my-api has uncommitted changes (1 file). The agent will edit files here; commit or stash first if you want to be able to roll back.
```

or `Note: ... isn't a git repository, so the agent's changes there can't
be rolled back with git.`

**Cause:** the agent edits files in place, and with uncommitted changes
(or no git) you can't undo its edits with git. It is only a warning; the
task continues.

**Fix:** stop the task (Ctrl-C) and run `git commit` or `git stash`, then
start again. To turn the warning off, set `CERTO_NO_WORKTREE_WARNING=1`.

### The agent writes to the wrong path

**You see:** errors like "Read-only file system", or files created in an
odd place such as `/HELLO.txt`.

**Cause:** the agent's file editor needs absolute paths, and the model
guessed one that doesn't exist on your machine.

**Fix:** use `--project NAME`, so the workspace is a clear absolute path,
and mention paths relative to the project in the task.

### `certo init` says a file already exists

**You see:** `Error: .../certo/.env already exists (...). Use --force to
replace it.`, or `... is not empty`.

**Cause:** `init` never replaces settings or files without asking. With
`--yes`, or without a terminal, it can't ask.

**Fix:** run `certo init` in a terminal to be asked, or add `--force`.

### Docker

See the table in [Run in Docker](guides/run-in-docker.md#if-it-doesnt-work).
