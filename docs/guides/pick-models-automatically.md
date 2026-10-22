# Pick models automatically

This guide shows how to give Certo a list of models and let it choose the
best one for each task, with fallback to the next model when one fails. It
is for people who use several models and want cheap models on simple tasks
and strong models on hard ones.

The choice uses simple keyword rules and scores you write. It makes no
extra model call.

## 1. Create the model files

**The quick way:** run `certo init models`. It offers the models this
computer can reach, tests each one, writes the files below and asks
whether to use `--auto-model` for every run. See
[the reference](../reference/commands.md#certo-init-models). The rest of
this section is what it writes, for when you want to edit the files
yourself. After a Certo upgrade, `certo models update` adds the example
list's new models and ratings to your copy, keeping your edits.

`--auto-model` uses three files, and Certo ships each only as an example:

- **`models_list.yaml`**, the catalog: the models and their ratings. No
  keys.
- **`models.yaml`**, your personal settings: the models you use, by name,
  each with its key or server address. It holds keys: keep it out of git,
  like `.env`.
- **`task_profiles.yaml`**, the kinds of task and what matters for each.
  Optional: without it, every task ranks the models with no weights, so
  the order of `models_list.yaml` decides.

Copy the examples into your user settings folder (or into a project
folder, which then overrides them). An `--auto-model` run without the
files prints the exact commands for your installation (so does `certo
check`, once one of the two required files exists):

```bash
cp <examples>/models_list.yaml.example ~/.config/certo/models_list.yaml
cp <examples>/models.yaml.example ~/.config/certo/models.yaml
cp <examples>/task_profiles.yaml.example ~/.config/certo/task_profiles.yaml
```

The list describes the models. A short one:

```yaml
# models_list.yaml
models:
  - name: claude-sonnet
    model: anthropic/claude-sonnet-5-5
    description: "Strong, well-rounded coding model."
    ratings: {reasoning: 4, precision: 4, code: 5, cost: 2}

  - name: local-coder
    model: ollama/qwen3-coder:30b
    description: "Free, local, weaker on hard tasks."
    ratings: {reasoning: 1, precision: 2, code: 1, cost: 5}
```

The task profiles say which ratings matter for which kind of task:

```yaml
# task_profiles.yaml
task_profiles:
  debugging:
    triggers: [fix, bug, crash, "failing test"]
    weights: {reasoning: 3, precision: 2, code: 2, cost: 0.5}
  default:
    weights: {reasoning: 1, cost: 1, precision: 1, code: 1}
```

`models.yaml` picks the ones you use and adds what's personal:

```yaml
# models.yaml
models:
  - name: claude-sonnet
    api_key: "${ANTHROPIC_API_KEY}"   # the key is in your settings file
  - name: local-coder
    base_url: "http://localhost:11434"
```

- Only the models listed in `models.yaml` are used. `activated: false`
  keeps an entry there without using it.
- Keep each key in your settings file (`ANTHROPIC_API_KEY=sk-ant-...` in
  `~/.config/certo/.env`) and name it in `models.yaml` as
  `"${ANTHROPIC_API_KEY}"`. See [the reference](../reference/models-yaml.md#modelsyaml).
- To add a model, add it to `models_list.yaml` first, then name it in
  `models.yaml`. To change a rating for yourself only, override it in
  `models.yaml` (`ratings: {code: 4}`).
- Run `certo check` to see what Certo makes of the files: the active
  models and every error or warning. `certo check --models` also tests
  each active model with a real request.
- On every rating, **higher is better, including `cost`**: `cost: 5` means
  cheap.

Every field is in the [reference](../reference/models-yaml.md).

## 2. Run with `--auto-model`

```bash
certo "Fix the failing test in payments.py" --auto-model
```

Or set `CERTO_MODEL_SELECTION=auto` in your settings. Where Certo finds
the files is in the [reference](../reference/models-yaml.md#where-certo-looks).

`CERTO_LLM_MODEL` must still be set: Certo checks the normal settings
before it reads the model files. Problems in them are reported the same
way for every command: errors stop the run, warnings are printed (see
[Checks](../reference/models-yaml.md#checks)).

With `--project NAME`, a model-file configuration error leaves no new
project folder or registry entry. An existing project folder is kept.

## How a model is chosen

1. **Classify the task.** Certo looks for each profile's `triggers` in the
   task's first line with text: a task file's title, or the whole task
   when it is one line. A trigger matches a whole word, or its plural, in
   any case. The first profile in the file that matches wins. If none
   matches, it uses the profile named `default`. `MODEL_DECISIONS.md` says
   which word matched.
2. **Score every active model.** The score is the sum of
   `rating × weight` over the profile's weights.
3. **Run the best one.** Models are ranked by score, once, at the start.
   Ties keep the order of the file. A profile can name a model instead
   (`model:`, see below): that model runs first, and the others follow by
   score.
4. **Fall back when needed.** Certo moves to the next model in the ranking
   when the current one:
   - fails at the provider (bad key, rate limit, outage, context too long),
     or
   - makes a fix attempt that still fails Certo's checks, or
   - uses all its steps (`CERTO_MAX_ITERATIONS`) with the checks still
     failing. The next model carries on in the same conversation, with a
     fresh set of steps. If the checks pass, nothing switches: the task is
     `verified`.

When every model has been tried, the task ends as it would without
automatic selection.

With `--interactive` as well, Certo shows the ranked list and asks which
model to use, with the best one as the default.

## Always use one model for a kind of task

When you already know which model you want for a profile, name it with
`model:` instead of tuning the weights until it wins:

```yaml
# task_profiles.yaml
task_profiles:
  debugging:
    triggers: [fix, bug, crash, "failing test"]
    model: claude-sonnet-5-5        # always first for debugging tasks
    weights: {reasoning: 3, precision: 2, code: 2, cost: 0.5}
```

- The name is a model in `models_list.yaml`, as in a ladder.
- It runs first only when it is enabled in `models.yaml`. If it isn't
  (no key for it, or `activated: false`), the weights pick the model as
  before, and `MODEL_DECISIONS.md` says why the named model wasn't used.
- If it fails (the provider refuses it, or a fix attempt still fails the
  checks), Certo moves on to the model the weights rank first, and so on.
- `certo check` reports a name that isn't in `models_list.yaml` as an
  error, and a model that isn't enabled as a warning.

## Preview and tune the choice

You don't need to run a task to see which model it gets. `certo check`
lists every task profile with the first three models it would try:

```text
  Task profiles (--auto-model), checked in this order:
    debugging, title has: fix, bug
      gpt-luna (named by the profile, score 13), claude-sonnet (score 20), qwen-local (score 9)
    scaffolding, title has: scaffold
      qwen-local (score 10), gpt-luna (score 8), claude-sonnet (score 4)
    default, when no other profile matches
      claude-sonnet (score 12), gpt-luna (score 11), qwen-local (score 10)
```

For one task, `certo check --task` shows the profile it matches and the
whole order. Give it the task the way you would give it to a run (text
or a task file):

```bash
certo check --task "Write a Wordle game in Python"
certo check --task tasks/wordle.md
```

```text
Task title: Write a Wordle game in Python
Profile: default (no other profile's trigger word is in the title)
Models, in the order --auto-model tries them (ranked by the profile's weights):
  1. claude-sonnet (score 12)
  2. gpt-luna (score 11)
  3. qwen-local (score 10)
The first model runs the task. The next one takes over if its provider fails, or if a fix attempt still fails Certo's checks.
```

Neither one calls a model, so you can change `task_profiles.yaml` and run
them again as often as you like:

- **The wrong profile?** Add a trigger word to the profile you want, or
  reword the task's title. Remember that the first matching profile wins.
- **The wrong first model?** Raise the weight of the axis that model is
  rated well on, or name it with `model:`.
- **The wrong fallback?** The second line is the model that takes over
  when the first one fails. If you want a stronger model there, raise its
  axis in the weights: `model:` only fixes the first one.

## See what was chosen and why

Before the verdict, the output says which model did the work:

```text
Model used: claude-sonnet (effort default) (see MODEL_DECISIONS.md for the full history)
```

`MODEL_DECISIONS.md` in the project folder records every decision, even
when the task failed. For the task and file above:

```markdown
# Model Decisions

## initial — 2026-10-19T20:29:17.140969+00:00

Reason: Task classified as 'debugging': "fix" in the task's first line ('Fix the failing test in payments.py') (weights: {'reasoning': 3.0, 'precision': 2.0, 'code': 2.0, 'cost': 0.5}). Model order: ranked by the profile's weights.

Task profile: `debugging` (weights: {'reasoning': 3.0, 'precision': 2.0, 'code': 2.0, 'cost': 0.5})

Ranked candidates:
- **claude-sonnet (effort default)** (score 31.00)
- local-coder (effort default) (score 11.50)

Chosen: **claude-sonnet (effort default)**
```

Each fallback adds a section of its own, with the reason for the switch.

## Limits

- The ranking is computed once per task. Falling back moves to the next
  best fit for this kind of task, which is not always a stronger model.
- Under `--execution docker`, the first choice works, but Certo can't
  switch models in the middle of a task.

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
