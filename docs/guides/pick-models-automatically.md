# Pick models automatically

This guide shows how to give Certo a list of models and let it choose the
best one for each task, with fallback to the next model when one fails. It
is for people who use several models and want cheap models on simple tasks
and strong models on hard ones.

The choice uses simple keyword rules and what each kind of task needs.
It makes no extra model call.

## 1. Create the model files

**The quick way:** answer Yes when `certo init` asks "Set up more models
now?", or run `certo init models` at any time. It offers the models this
computer can reach, tests each one, writes the files below and asks
whether to use `--auto-model` for every run. See
[the reference](../reference/commands.md#certo-init-models).

**You need one file, `models.yaml`:** the models you use, by name, each
with its key or server address. It holds keys: keep it out of git, like
`.env`. Certo has its own model list (every model with its ratings) and
its own task profiles (the kinds of task and what each needs), read from
the package, so a new Certo release brings their updates to you.

Two more files are optional, for what is different for you:

- **`models_list.yaml`:** a model Certo's list doesn't have, or a rating
  you disagree with. Give only what changes.
- **`task_profiles.yaml`:** a kind of task of your own, different needs,
  or the model you want first for a kind of task. `certo init models
  --profiles` writes that last one for you:

```bash
certo init models --profiles
```

For each kind of task it shows the 3 models that fit best, and you pick
the one that goes first, another of your models, or "Let the ratings
decide". It can also leave your local models out of `--auto-model`, for
example during the day when the machine running them is off.

Files in a project folder add to or change yours, model by model: see
[Where Certo looks](../reference/models-yaml.md#where-certo-looks).
A full `models_list.yaml` copied before 0.2.3 hides Certo's newer values:
`certo models update` slims it to your own changes.

`models.yaml` names the models you use, by their names in Certo's list,
and adds what's personal:

```yaml
# models.yaml
models:
  - name: claude-sonnet-5-5
    api_key: "${ANTHROPIC_API_KEY}"   # the key is in your settings file
  - name: qwen3.8-27b-local
    base_url: "http://localhost:11434"
```

A `models_list.yaml` of your own holds only what Certo's list doesn't:

```yaml
# models_list.yaml
models:
  - name: my-finetune                 # a model Certo doesn't know
    model: openrouter/me/my-finetune
    ratings: {reasoning: 3, precision: 3, code: 4, writing: 3, speed: 4, cost: 4}
  - name: qwen3.8-27b-local           # one rating changed; the rest stays Certo's
    ratings: {speed: 2}
```

And a `task_profiles.yaml` of your own only what differs from Certo's
profiles, which say what each kind of task needs:

```yaml
# task_profiles.yaml
task_profiles:
  build:
    model: claude-haiku-5-5           # always first for builds
  docs:
    needs: {writing: 4}               # stricter than Certo's
```

- Only the models listed in `models.yaml` are used. `activated: false`
  keeps an entry there without using it.
- Keep each key in your settings file (`ANTHROPIC_API_KEY=sk-ant-...` in
  `~/.config/certo/.env`) and name it in `models.yaml` as
  `"${ANTHROPIC_API_KEY}"`. See [the reference](../reference/models-yaml.md#modelsyaml).
  Keys already written out in `models.yaml`? `certo models secure` moves
  them for you.
- To add a model, add it to `models_list.yaml` first, then name it in
  `models.yaml`. To change a rating for yourself only, override it in
  `models.yaml` (`ratings: {code: 4}`).
- Run `certo check` to see what Certo makes of the files: the active
  models and every error or warning. `certo check --models` also tests
  each active model with a real request.
- On every rating, **higher is better, including `cost`**: `cost: 5` means
  cheap.

Every field is in the [reference](../reference/models-yaml.md).

**For one project only:** `certo models choose --project NAME` lets you
tick the models that project may use, shows the order `--auto-model`
would try them and the ladder `--escalate` would climb, recommends one,
and writes `certo-models.yaml` in the project. No YAML to write by
hand; runs in that project then use it. See
[the command](../reference/commands.md#certo-models-choose).

## 2. Run with `--auto-model`

```bash
certo "Fix the failing test in payments.py" --auto-model
```

Or set `CERTO_MODEL_SELECTION=auto` in your settings. Where Certo finds
the files is in the [reference](../reference/models-yaml.md#where-certo-looks).

`CERTO_LLM_MODEL` and `CERTO_LLM_API_KEY` aren't needed: the model
files name every model and its key. Problems in them are reported the
same way for every command: errors stop the run, warnings are printed
(see [Checks](../reference/models-yaml.md#checks)).

With `--project NAME`, a model-file configuration error leaves no new
project folder or registry entry. An existing project folder is kept.

## How a model is chosen

1. **Classify the task.** Certo looks for each profile's `triggers` in the
   task's first line with text: a task file's title, or the whole task
   when it is one line. A trigger matches a whole word, or its plural, in
   any case. The first profile in the file that matches wins. If none
   matches, it uses the profile named `default`. `MODEL_DECISIONS.md` says
   which word matched. A task written in milestones is classified again
   for each milestone: by the milestone's own title first (`## Milestone
   2: Fix the flaky tests` is `debugging`), and by the task's title when
   the milestone's has no trigger word. Only titles are read, never the
   text under them: a spec that says "raise an error" isn't a debugging
   task.
2. **Find the models that fit.** A profile says what its kind of task
   needs, as a minimum rating per axis (`needs: {code: 4}`). A model
   fits when it is rated at least that on every axis listed.
3. **Run the least costly of them.** Among the models that fit, the one
   with the highest `cost` rating (the cheapest) goes first. A profile can
   name a model instead (`model:`, see below): that model runs first.
   If its work fails, the next model is a more capable one that also
   fits. So a local model wins where it is good enough (leave `speed`
   out of `needs` where slow is fine), and Opus or Fable only where
   nothing cheaper fits. Profiles written before 0.2.3 with `weights:`
   still rank by a weighted score, as before.
4. **Skip a local model that can't be reached.** Before a local model
   (Ollama, or another server on this machine or network) gets work, at
   the start and at every fallback, Certo asks its server, in a few
   seconds, whether it is up and has the model. If not, it moves to the
   next model and says why:

   ```text
   Certo: skipping qwen3.8-27b-local: the Ollama server at turing.local:11434 didn't answer. Using claude-haiku-5-5.
   ```

   Cloud models aren't asked (that would be a paid call); a cloud
   provider that refuses fails at once and is handled in the next step.
   The last model in the order is kept even when it can't be reached.
5. **Fall back when needed.** Certo moves to the next model in the ranking
   when the current one:
   - fails at the provider (bad key, rate limit, outage, context too long),
     or
   - leaves work that fails Certo's checks (the next model makes the fix
     attempt, and so on for each failed attempt), or
   - uses all its steps (`CERTO_MAX_ITERATIONS`) with the checks still
     failing. The next model carries on in the same conversation, with a
     fresh set of steps. If the checks pass, nothing switches: the task is
     `verified`.

When every model has been tried, the task ends as it would without
automatic selection.

With `--interactive` as well (or in the [interactive session](interactive-mode.md#the-interactive-session)),
Certo shows the ranked list with each model's ratings, and the first
sentence of the description for the first three, and asks which model
to use, with the best one as the default. Enter takes it; a number
takes another:

```text
  [0] qwen3.8-27b-local (recommended) — reasoning=1.8, precision=1.7, code=3.4, writing=1.7, speed=2, cost=5
      Alibaba Qwen3.8-27B dense (18GB, 256K context, text and image, thinking on by default; August 2026).
  [1] gpt-6-luna — reasoning=3.2, precision=3.5, code=3.6, writing=3.4, speed=4, cost=4.8
      OpenAI's cheapest current tier: $0.10 in / $0.50 out per 1M (Sept 2026, half of GPT-5.6 Luna).
  [2] claude-haiku-5-5 — reasoning=3.8, precision=2.4, code=4.4, writing=3.1, speed=4, cost=4.8
      $0.10 in / $0.50 out per 1M for prompts up to 100K tokens; 5x that ($0.50 / $2.50) above 100K.
  [3] gpt-6.1-terra — reasoning=4.9, precision=3, code=4.4, writing=3, speed=4, cost=4.3
  [4] claude-sonnet-5-5 — reasoning=4.8, precision=3.7, code=4.8, writing=4.3, speed=4, cost=3.1
  ...
Use recommended model [qwen3.8-27b-local]? [Y/n or a number]:
```

## Always use one model for a kind of task

When you already know which model you want for a profile, name it with
`model:` instead of changing the needs until it wins (`certo init models
--profiles` writes this line for you):

```yaml
# task_profiles.yaml
task_profiles:
  debugging:
    triggers: [fix, bug, crash, "failing test"]
    model: claude-sonnet-5-5        # always first for debugging tasks
    needs: {reasoning: 4, code: 4}
```

- The name is a model in `models_list.yaml`, as in a ladder.
- It runs first only when it is enabled in `models.yaml`. If it isn't
  (no key for it, or `activated: false`), the needs pick the model as
  before, and `MODEL_DECISIONS.md` says why the named model wasn't used.
- If it fails (the provider refuses it, or its work fails the checks),
  Certo moves on to the model the needs put first, and so on.
- `certo check` reports a name that isn't in `models_list.yaml` as an
  error, and a model that isn't enabled as a warning.

## Preview and tune the choice

You don't need to run a task to see which model it gets. `certo check`
lists every task profile with the first three models it would try:

```text
  Task profiles (--auto-model), checked in this order:
    debugging, title has: fix, bug, crash, failing test
      claude-sonnet (fits, cost 3), claude-haiku (below: reasoning 3 < 4, cost 4.9), gpt-luna (below: reasoning 3 < 4, code 3 < 4, cost 4.9), +1 more
    docs, title has: readme, documentation
      qwen-local (fits, cost 5), claude-haiku (fits, cost 4.9), gpt-luna (fits, cost 4.9), +1 more
    default, when no other profile matches
      claude-haiku (fits, cost 4.9), gpt-luna (fits, cost 4.9), claude-sonnet (fits, cost 3), +1 more
```

Here the local model goes first only for docs: it is good enough at
writing, and the profile doesn't need speed. For a bug, only Sonnet
meets "reasoning 4"; for anything else, Haiku is the least costly model
that codes well enough.

For one task, `certo check --task` shows the profile it matches and the
whole order. Give it the task the way you would give it to a run (text
or a task file):

```bash
certo check --task "Fix the failing test in payments.py"
certo check --task tasks/wordle.md
```

```text
Task title: Fix the failing test in payments.py
Profile: debugging ("fix" is in the title)
Models, in the order --auto-model tries them (the least costly of the models that meet the needs (reasoning 4+, code 4+); fallbacks climb):
  1. claude-sonnet (fits, cost 3)
  2. claude-haiku (below: reasoning 3 < 4, cost 4.9)
  3. gpt-luna (below: reasoning 3 < 4, code 3 < 4, cost 4.9)
  4. qwen-local (below: reasoning 3 < 4, code 2 < 4, cost 5)
The first model runs the task. The next one takes over if its provider fails, or makes the fix attempt when the current model's work fails Certo's checks.
```

For a task file written in milestones, it also gives each milestone's
profile and first model. With Certo's profiles, `tasks/sky-hopper.md`
ends with:

```text
It runs milestone by milestone. Each milestone is classified by its own title first, then by the task's:
  1. The level and the camera: build ("game" in the task's title), claude-haiku-5-5 first
  2. Running and jumping: build ("game" in the task's title), claude-haiku-5-5 first
  3. Parallax, coins and blocks: build ("game" in the task's title), claude-haiku-5-5 first
  4. Enemies, the flag and the next level: build ("game" in the task's title), claude-haiku-5-5 first
```

Neither one calls a model, so you can change `task_profiles.yaml` and run
them again as often as you like:

- **The wrong profile?** Add a trigger word to the profile you want, or
  reword the task's title. Remember that the first matching profile wins.
- **A model too strong (or too weak) goes first?** Lower (or raise) the
  profile's needs: the first model is the least costly one that meets
  them. Or name it with `model:`.
- **A local model where you need answers fast?** Add `speed: 4` to the
  profile's needs.
- **Ratings out of date?** Run
  [`certo models refresh`](../reference/commands.md#certo-models-refresh):
  it rates every model from current benchmark data, list prices and how
  your own runs ended, and shows which models now fit each kind of task.
- **A model rated wrong for your use?** Change its rating for yourself in
  `models.yaml` (`ratings: {code: 4}`). Your ratings always win over the
  computed ones.

## See what was chosen and why

Before the verdict, the output says which model did the work:

```text
Model used: claude-sonnet (effort default) (see MODEL_DECISIONS.md for the full history)
```

`MODEL_DECISIONS.md` in the project folder records every decision, even
when the task failed. To have it explained, run
`certo ask --mine "why did my run pick this model?"` in the project folder
([questions about your setup](../reference/commands.md#questions-about-your-setup)).
For the task and file above:

```markdown
# Model Decisions

## initial — 2026-11-14T19:30:05.485989+00:00

Reason: Task classified as 'debugging': "fix" in 'Fix the failing test in payments.py' (needs: {'reasoning': 4.0, 'code': 4.0}). Model order: the least costly of the models that meet the needs (reasoning 4+, code 4+); fallbacks climb.

Task profile: `debugging` (needs: {'reasoning': 4.0, 'code': 4.0})

Ranked candidates:
- **claude-sonnet (effort default)** (shortfall 0.00)
- claude-haiku (effort default) (shortfall 1.00)
- gpt-luna (effort default) (shortfall 2.00)
- qwen-local (effort default) (shortfall 3.00)

Chosen: **claude-sonnet (effort default)**
```

The shortfall says how far each model is below the needs, added up over
the axes: 0 means it fits.

Each fallback adds a section of its own, with the reason for the switch.

A task written in milestones runs one milestone at a time, and each
milestone is classified on its own. `MODEL_DECISIONS.md` then has one
section per milestone, `## Milestone 2 of 4: <its title>`, holding that
milestone's decisions. Running a milestone again replaces its section and
removes those of the milestones after it.

## Limits

- The ranking is computed once per task. With `needs`, falling back
  climbs to a stronger model that fits; with a profile that has only
  `weights`, it moves to the next best score, which is not always a
  stronger model. To climb a fixed list of models, use
  [escalation](escalate-between-models.md).
- The classification reads only titles (task and milestone), so "rename
  a variable" and "rewrite the physics engine" can get the same profile.
- Under `--execution docker`, the first choice works, but Certo can't
  switch models in the middle of a task, and doesn't check whether a
  local model can be reached.

## Automatic choice or escalation?

`--auto-model` picks the best fit for each task up front and switches only
on errors or failed fix attempts, inside one conversation. To run a task
on a list of models in order, moving to the next only when a model's work
fails verification or its provider fails (for example a cheap model
first), use [escalation](escalate-between-models.md) instead:
`--escalate`. The two can't be combined. How they differ, with use cases:
[Auto-model or escalation](../concepts/auto-model-or-escalation.md).

## Related

- [The model files](../reference/models-yaml.md)
- [Escalate between models](escalate-between-models.md)
- [Run records and costs](run-records-and-costs.md): tokens and cost per model
