# The model files

The format of the files behind automatic model selection
(`--auto-model`), escalation (`--escalate`) and the benchmark
(`certo bench`). It is for looking things up; the guides are
[Pick models automatically](../guides/pick-models-automatically.md),
[Escalate between models](../guides/escalate-between-models.md) and
[Benchmark models and strategies](../guides/benchmark.md).

| File | Holds | Needed |
|---|---|---|
| `models_list.yaml` | The catalog: which models exist, their LiteLLM ids, descriptions and ratings. No keys, no addresses. | Always |
| `models.yaml` | Your personal settings: which models of the list you use, each with its API key or server address, whether it is activated, and any overrides. It holds keys: keep it out of git. | Always |
| `task_profiles.yaml` | The task profiles `--auto-model` chooses with. | Optional |
| `escalation.yaml` | The ladders `--escalate` climbs, and the settings for a derived ladder. Also read by `certo bench`. | Optional |

Certo reads them for `--auto-model` and `--escalate` (or
`CERTO_MODEL_SELECTION=auto` / `escalate`), for `certo check` and for
`certo bench`. With the default (manual) selection, none is read.

`task_profiles.yaml` and `escalation.yaml` each belong to one mode, so you
only need the one for the mode you use. Without `task_profiles.yaml`,
`--auto-model` ranks the enabled models with no weights, so the order of
`models_list.yaml` decides. Without `escalation.yaml`, `--escalate` builds
a ladder from the ratings.

## Start from the examples

Certo ships all four files only as examples, inside the package, and never
reads an example. Copy the ones you need and edit your copies:

```bash
cp <examples>/models_list.yaml.example ~/.config/certo/models_list.yaml
cp <examples>/models.yaml.example ~/.config/certo/models.yaml
cp <examples>/task_profiles.yaml.example ~/.config/certo/task_profiles.yaml   # for --auto-model
cp <examples>/escalation.yaml.example ~/.config/certo/escalation.yaml         # for --escalate
```

The quick way is `certo init models`, which writes the files for the
models it tested (see [Commands](commands.md#certo-init-models)). A new
Certo release may update the example list; `certo models update` brings
your copy up to date and keeps your changes (see
[Commands](commands.md#certo-models-update)), and `certo models check`
compares its prices and cost ratings with LiteLLM's price list (see
[Commands](commands.md#certo-models-check)). A run
that needs a missing file prints the exact `cp` command, with the
examples folder of your installation; so does `certo check` when one of
the two required files exists. With neither, `certo check` says to run
`certo init models`. It also lists the two optional files it found. In the repository the examples are in
[src/certo/examples/](../../src/certo/examples/models_list.yaml.example)
(`models_list.yaml.example`, `models.yaml.example`,
`task_profiles.yaml.example`, `escalation.yaml.example`). A new Certo
release can update the examples; it never touches your copies, so add
models, change ratings and write ladders in your copies freely.

## Where Certo looks

Each file is looked up on its own.

**A path a setting names is used alone:** `CERTO_MODELS_LIST_FILE`,
`CERTO_MODELS_FILE`, `CERTO_TASK_PROFILES_FILE` and
`CERTO_ESCALATION_FILE` (for `certo bench`: `models_list_file`,
`models_file` and `escalation_file` in its benchmark file). A setting
that names a file that doesn't exist is an error.

**Otherwise the file is read in layers,** lowest first:

1. the user settings folder, next to the user `.env`:
   `~/.config/certo/` (or `$XDG_CONFIG_HOME/certo/`);
2. the current folder;
3. the project folder, with `--project NAME`.

Each layer adds to the one below, or changes it, **by name**: a model in
`models_list.yaml` or `models.yaml` changes only the fields it gives
(`ratings` axis by axis), and a task profile or ladder with the same name
replaces the one below. Anything new is added. So a project needs only
what is different:

```yaml
# projects/game/models_list.yaml: Terra codes well enough for this game
models:
  - name: gpt-6.1-terra
    ratings: {code: 5}
```

```yaml
# projects/game/models.yaml: no Opus here; keys still come from your file
models:
  - name: claude-opus-5-5
    activated: false
```

`replace: true` at the top of a file makes it hide the layers below it,
as every file did before Certo 0.2.3. `certo check` (with `--project
NAME` for a project) prints each file and what each layer above the
lowest changes or adds:

```text
  List: /home/you/.config/certo/models_list.yaml
    + /home/you/certo-workspace/projects/game/models_list.yaml: changes gpt-6.1-terra
```

A project can also have its own choice, [`certo-models.yaml`](#certo-modelsyaml),
at its top. A run reads it from the `--project` folder (or the folder
the run works in), as its task profiles and escalation file, unless a
setting names those files.

## `models_list.yaml`

```yaml
models:          # required, a non-empty list
  - name: qwen3-coder-local
    model: ollama/qwen3-coder:30b
    timeout_seconds: 900
    description: ...
    ratings: {reasoning: 1, precision: 2, code: 1, cost: 5}
```

| Model field | Required | Meaning |
|---|---|---|
| `name` | yes | A short, unique name. `models.yaml` and ladders refer to the model by it. Used in logs, in the `Model used:` line and in `MODEL_DECISIONS.md`. |
| `model` | yes | The LiteLLM model id, as in `CERTO_LLM_MODEL`. |
| `reasoning_effort` | no | As `CERTO_LLM_REASONING_EFFORT`. Empty means the default. |
| `timeout_seconds` | no | As `CERTO_LLM_TIMEOUT_SECONDS`: how long one call to this model may take, a whole number of seconds. Default `300`; `0` means no limit. |
| `context_tokens` | no | As `CERTO_LLM_CONTEXT_TOKENS`: the model's context window, in tokens. Default `0`: what the provider reports, or for Ollama what the server gives the model. For Ollama, a set value is asked from the server. |
| `description` | no | Shown when `--interactive` asks you to pick a model. |
| `ratings` | no | A map of axis name to number, usually 1 to 5. Decimals are allowed: the example list's `cost` has one, worked out from the price (the formula is at the top of the example). |

`api_key`, `base_url` and `activated` are not allowed here: they are
personal and go in `models.yaml`.

## `models.yaml`

```yaml
models:          # required, a non-empty list
  - name: qwen3-coder-local          # a name from models_list.yaml
    base_url: http://localhost:11434
  - name: gpt-6-luna
    api_key: "${OPENAI_API_KEY}"     # read from your settings file
  - name: claude-sonnet-5-5
    api_key: "${ANTHROPIC_API_KEY}"
    activated: false
    ratings: {code: 4}               # an override
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | The `name` of a model in `models_list.yaml`. A name the list doesn't have is an error: add new models to the list. |
| `api_key` | no | As `CERTO_LLM_API_KEY`. Empty means no key. Best written as `"${NAME}"`, the name of a variable in your settings file (see below). |
| `base_url` | no | As `CERTO_LLM_BASE_URL`, for Ollama and other local or self-hosted servers. Empty means the provider's default. Can use `${NAME}` too. |
| `activated` | no | `true` (default) or `false`. A `false` entry stays in the file but is never used. |
| `ratings` | no | Overrides, axis by axis: `{code: 4}` changes only `code`; the other axes keep the list's values. |
| `reasoning_effort`, `timeout_seconds`, `context_tokens`, `description` | no | Overrides of the list's values. |

**Only the models listed here, and not `activated: false`, are ever
used**: not in `--auto-model`, not in an escalation ladder, and not in
`certo bench`. A model that is only in `models_list.yaml` is known (ladders
may name it) but skipped.

Each model is complete on its own: settings it leaves empty are **not**
taken from `CERTO_LLM_*`. A local model with no `api_key` never gets the
key of another provider. With `--escalate` or `--auto-model`,
`CERTO_LLM_MODEL` and `CERTO_LLM_API_KEY` aren't needed.

**Keys belong in the settings file.** Write `api_key: "${ANTHROPIC_API_KEY}"`
and put the key itself in your settings file (`~/.config/certo/.env`, or
`.env` in the project folder), as `ANTHROPIC_API_KEY=sk-ant-...`. Each key
is then in one place, and `models.yaml` holds no secret. Certo reads
`${NAME}` from the environment and the settings files, in the same order
as every other setting. When the variable isn't set, the model is left
out, and `certo check` and the run say which variable is missing; the
text `${NAME}` is never sent as a key.

A key written out in `models.yaml` still works, but `certo check` and
every run warn about it. `certo models secure` moves each one to your
settings file and writes `"${NAME}"` in its place (see
[the command](commands.md#certo-models-secure)).

Before version 0.1.10 everything was in `models.yaml`. An old-style file
(with model ids, `task_profiles` or `escalation`) is an error that says
what to move where.

## Ratings: higher is always better

The axis names are yours. The example list uses `reasoning`, `precision`,
`code`, `writing`, `speed` and `cost`, but you can add any name, such as
`latency`. Its `writing` and `speed` ratings are estimates for now (the
comments at its top say how they were set); rate your own local models'
`speed` for your machine in `models.yaml`. `speed` says how fast answers
come, not how good they are, so it never counts as capability (for
example in an escalation ladder).

On every axis, a higher number must mean "more of what I want". For `cost`
this means **cost-effectiveness**: `cost: 5` is a cheap (or free, local)
model, `cost: 1` an expensive one. The example list explains the scale
behind its numbers in its comments.

## `task_profiles.yaml`

A profile says what a kind of task needs, for `--auto-model`. The file
has one top-level key, `task_profiles`:

```yaml
task_profiles:
  debugging:
    triggers: [fix, bug, crash]
    model: claude-sonnet-5-5         # optional
    needs: {reasoning: 4, code: 4}
  docs:
    triggers: [readme, documentation]
    needs: {writing: 3}              # no speed: a slow local model is fine
  default:
    needs: {code: 3}
```

| Field | Meaning |
|---|---|
| `triggers` | A list of words or phrases. A profile matches when one of them appears in the task's first line with text (a task file's title, or the whole task when it is one line), as a whole word or with a plural `s`/`es`, in any case. |
| `needs` | A map of axis name to the minimum rating a model must have for this kind of task. See "Choosing by fit" below. |
| `weights` | A map of axis name to number, for a profile without `needs` (the rule before 0.2.3, see "Scoring"). A profile with `needs` ignores it. |
| `model` | Optional. The name of a model in `models_list.yaml` to run first for this profile. Used only when that model is enabled in `models.yaml`; otherwise the needs (or weights) decide, and `MODEL_DECISIONS.md` says why. The needs (or weights) still order the fallbacks after it. A name that isn't in `models_list.yaml` is an error in `certo check`; a model that isn't enabled is a warning. |

**Choosing the profile.** The profiles are tried in the order of the file,
skipping the one named `default`. The first that matches wins. If none
matches, the `default` profile is used. Put specific profiles before broad
ones.

**Choosing by fit** (a profile with `needs`). A model **fits** when its
rating on every axis in `needs` is at least the minimum; an axis it
doesn't rate counts as 0, so it doesn't fit (`certo check` warns about
it). Then:

1. The first model is **the least costly of the models that fit**: the
   highest `cost` rating. On a tie, the one rated higher on the needed
   axes goes first, then the order of the list.
2. The next models are the other models that fit, **climbing in
   capability** (the needed axes first, then the sum of every rating but
   `cost` and `speed`): if the first model's work fails the checks, a
   stronger one takes over.
3. Last come the models that don't fit, the closest first. A provider
   failure can still reach them.

If no model fits, the closest one goes first (the smallest total
shortfall below the needs), and `MODEL_DECISIONS.md` says so. Neither
cost nor capability wins everything: a cheap local model goes first where
it is good enough and slowness is acceptable (no `speed` in `needs`), and
a frontier model only where nothing cheaper fits. `MODEL_DECISIONS.md`
lists each model with its `shortfall` (0: it fits).

**Scoring** (a profile with only `weights`). For each active model:

```text
score = sum of rating[axis] × weight[axis], over the profile's weights
```

An axis the model doesn't rate counts as 0. Models are ranked by score,
highest first; equal scores keep the order of the list. If no profile
matches and there is no `default`, every model scores 0 and the order of
the list decides.

## `escalation.yaml`

Settings for escalation: running a task on the first model of a ladder,
and moving to the next one only when Certo's verification shows the model
couldn't finish, or its provider fails. The file has one top-level key,
`escalation`, and every field in it is optional. A file with only
comments sets nothing. The guide, with how a derived ladder is computed,
is [Escalate between models](../guides/escalate-between-models.md).

| Field | Default | Meaning |
|---|---|---|
| `cost_axis` | `cost` | The rating axis that means cost-effectiveness. A model's capability, for escalation, is the sum of its ratings on every other axis (usually `reasoning + precision + code`). A derived ladder uses the cost axis to start from the cheapest models and to leave out a model that another one beats at the same price or less. |
| `max_rungs` | `3` | The longest ladder Certo builds from the ratings. A whole number, at least 2. |
| `ladders` | none | Ladders you write yourself, by name. |

**A ladder** is a list of rungs, tried in order:

```yaml
escalation:
  ladders:
    default:
      - model: qwen-local      # a name from models_list.yaml
        retries: 1             # optional
        reasoning_effort: ""   # optional
      - model: gpt-luna
      - model: claude-sonnet
```

| Rung field | Required | Meaning |
|---|---|---|
| `model` | yes | The `name` of a model in `models_list.yaml`. |
| `retries` | no | Fix attempts on this rung after a failed check. Default: `CERTO_MAX_VERIFY_RETRIES`. |
| `reasoning_effort` | no | Reasoning effort for this rung only, instead of the model's own. |

To set an option for a ladder, write it as a mapping with its rungs under
`rungs`:

```yaml
    local-only:
      escalate_on_acceptance_failed: true
      rungs:
        - model: qwen-local
        - model: gemma-local
          reasoning_effort: max
```

`escalate_on_acceptance_failed` (default `false`) also moves to the next
rung when a required acceptance check fails.

A ladder named `default` is the one used when no ladder name is given.
With no ladder at all, Certo builds one from the enabled models' ratings.
A rung whose model isn't enabled in `models.yaml` is skipped.

## `certo-models.yaml`

A project's own choice of models, written by
[`certo models choose`](commands.md#certo-models-choose) at the
project's top. It holds names only, never keys: the keys stay in your
`models.yaml`, so the file can be committed and shared.

```yaml
use: [claude-haiku-5-5, gpt-6-luna, gpt-6.1-terra]
strategy: auto
task_profiles:
  build:
    triggers: [build, implement, app, application, game, website, feature]
    needs: {code: 4.0}
  # ... the other kinds of task
escalation:
  ladders:
    default:
    - {model: claude-haiku-5-5}
    - {model: gpt-6.1-terra}
```

| Field | Meaning |
|---|---|
| `use` | The models runs in this project may use, by name. Every other model is left out. A name that isn't enabled in your `models.yaml` is left out with a warning. Without `use`, every enabled model. |
| `strategy` | `auto` (as `--auto-model`) or `escalate` (as `--escalate`). It applies to every run in the project, unless a flag (`--auto-model`, `--escalate`, `--model`) or `CERTO_MODEL_SELECTION` chooses. |
| `task_profiles` | As in [`task_profiles.yaml`](#task_profilesyaml). `certo models choose` writes the example profiles, each with what its kind of task needs. |
| `escalation` | As in [`escalation.yaml`](#escalationyaml). `certo models choose` writes the ladder Certo derives from the chosen models, as `default`. |

`certo check`, run in the project folder, says it uses the file.

## Moving from one file (0.1.19 and earlier)

Up to 0.1.19, the task profiles and the ladders were sections of
`models_list.yaml`. Up to 0.1.25 Certo still read them there, with a
warning. Since 0.1.26 it stops instead, at every run and in
`certo check`:

```text
  Task profiles: none (optional, for --auto-model)
  Escalation: none (optional, for --escalate)
  Error: .../models_list.yaml has the 'task_profiles:' section. Since 0.1.20 it belongs in its own file, task_profiles.yaml, next to models_list.yaml, and since 0.1.26 it is no longer read here: move the section there as it is. See docs/reference/models-yaml.md#moving-from-one-file-0119-and-earlier.
```

To move, cut the whole `task_profiles:` section, with its key, into a new
`task_profiles.yaml`, and the `escalation:` section into `escalation.yaml`,
next to your `models_list.yaml`. Nothing inside a section changes, and
neither section may stay in `models_list.yaml`, even when its own file is
there.

## Checks

Every command that reads the files checks them the same way. Errors stop
the command; warnings are printed, and the command runs.

Errors:

- a required file is missing, a file a setting names doesn't exist, a
  file is not valid YAML, `task_profiles.yaml` or `escalation.yaml` holds
  anything but its one key, `models` is missing or empty, an
  entry has no `name` (or, in the list, no `model`), a rating or weight is
  not a number, or a field has the wrong type or an unknown name;
- `models_list.yaml` has an `api_key`, `base_url` or `activated`, or a
  `task_profiles:` or `escalation:` section (see
  [Moving from one file](#moving-from-one-file-0119-and-earlier));
- `models.yaml` is in the old single-file format;
- two models in the list share a name, or `models.yaml` lists one twice;
- `models.yaml` names a model the list doesn't have;
- no model is enabled (none listed in `models.yaml`, or all
  `activated: false`);
- a ladder rung names a model that doesn't exist (the message lists the
  names that do);
- a ladder lists the same model twice with the same settings (the same
  model with a different `reasoning_effort` is allowed);
- a rung has a negative `retries`;
- `escalation.cost_axis` is set, and no model has a rating with that name;
- a task profile's `model` names a model that doesn't exist;
- a ladder has no usable rung.

A problem in a part that the run doesn't use is a warning instead, and
the run goes on: an `--auto-model` run doesn't stop for a ladder or
`escalation.cost_axis` problem, and an `--escalate` run doesn't stop for
a task profile's `model`. `certo check` and `certo bench` report them all
as errors.

Warnings:

- a task profile's `model` isn't enabled in `models.yaml`: the weights
  pick the model instead;
- a rung names a model that isn't in `models.yaml`, or has
  `activated: false`: the rung is skipped;
- a ladder has a single usable rung, so it can't escalate;
- an enabled model has no rating on an axis that a task profile weighs: it
  counts as 0;
- an enabled model has no `api_key` and no `base_url`: it works only if
  the provider's own key variable (such as `OPENAI_API_KEY`) is set;
- an `api_key` or `base_url` uses `${NAME}`, and that variable isn't set:
  the model is left out;
- a ladder goes from a more capable model to a less capable one
  (capability: the sum of the ratings except the cost axis). Allowed,
  since you may know better, but check the order.
