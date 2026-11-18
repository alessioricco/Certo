# Where model settings come from

Certo reads its model settings in layers. Certo's own list of models is
at the bottom; your settings go on top of it, then the folder you run in,
then the project. Each layer changes only what it names. This page
explains the layers, which file holds what, and how to see what Certo
used.

The exact lookup rules are in the reference:
[Where Certo looks](../reference/models-yaml.md#where-certo-looks).

## The layers

From the bottom up:

| Layer | Where | What it holds | Who changes it |
|---|---|---|---|
| 1. Certo's own | Inside the Certo package | Every model Certo knows, with its id, description and ratings (`models_list.yaml`), and the kinds of task with what each needs (`task_profiles.yaml`). After [`certo models refresh`](../reference/commands.md#certo-models-refresh), its computed ratings (`ratings.yaml`, in your settings folder) replace Certo's hand-written ones here, below your own files | Each Certo release, and `certo models refresh` |
| 2. Yours | `~/.config/certo/` (or `$XDG_CONFIG_HOME/certo/`) | Which models you use and their keys (`models.yaml`), the keys themselves (`.env`), and anything you want different from Certo's | You |
| 3. The current folder | The folder you run `certo` in | Changes for everything run from that folder | You |
| 4. The project | The `--project` folder | Changes for one project, and its own choice of models (`certo-models.yaml`) | You, or `certo models choose` |

A higher layer wins, **entry by entry**. If your `models_list.yaml` says
only this:

```yaml
models:
  - name: gpt-6.1-terra
    ratings: {reasoning: 4}
```

then Terra's reasoning is 4 for you, and everything else about Terra (its
id, its other ratings) and every other model still comes from Certo's
list. A layer that doesn't have a file adds nothing.

## Which file holds what

| File | Certo has its own? | What you put in yours |
|---|---|---|
| `models.yaml` | No | The models you use, by name, each with `api_key: "${NAME}"` or `base_url`. **The only file you need.** |
| `.env` | No | The keys (`OPENAI_API_KEY=...`) and your `CERTO_*` settings. |
| `models_list.yaml` | Yes | Only a model Certo doesn't know, or a rating you disagree with. |
| `task_profiles.yaml` | Yes | Only a kind of task of your own, different needs, or the model that goes first for a kind of task. |
| `escalation.yaml` | No | Your own ladders for `--escalate`. Without it, Certo builds one from the ratings. |
| `certo-models.yaml` | No (project only) | The models one project may use and its strategy, written by `certo models choose`. |

Keys never go in a model file: `models.yaml` names them as `${NAME}`, and
the value is in `.env`. `certo models secure` moves a key written out in
`models.yaml` into `.env` for you.

## Why layers

- **You get Certo's updates.** When a release adds a model or corrects a
  rating, you have it at once: your files hold only your own changes, so
  nothing old hides the new values. After `certo models refresh`, its
  computed ratings win over a release's until you refresh again (`certo
  check` says when the release ships newer data) or delete `ratings.yaml`.
- **A project changes only what is different.** A game project can turn
  off Opus, or rate a model higher, in two lines, without copying your
  keys or your other models.
- **You can always see why.** `certo check` shows each layer and what it
  changes.

## See what Certo used

`certo check` prints the files it read, lowest first, and what each layer
above Certo's changes or adds. With `--project NAME`, it reads them as a
run in that project would. For example:

```text
Model files:
  List: built into Certo 0.2.3
    + /Users/you/.config/certo/models_list.yaml: adds kimi-k2.7-code
  Personal settings: /Users/you/.config/certo/models.yaml
  Task profiles: built into Certo 0.2.3
  Escalation: none (optional, for --escalate)
```

Here the list is Certo's, plus one model of the user's own; the task
profiles are Certo's alone.

## Exceptions

- **A file a setting names is read alone.** `CERTO_MODELS_LIST_FILE`,
  `CERTO_MODELS_FILE`, `CERTO_TASK_PROFILES_FILE` and
  `CERTO_ESCALATION_FILE` (and the files a benchmark names) replace all
  the layers for that file. Benchmarks use this, so their results don't
  change when Certo's list does.
- **`replace: true`** at the top of a file hides the layers below it,
  Certo's own included. Computed ratings go only on Certo's own list, so
  a list a setting names, or one with `replace: true`, gets none.
- **A full copy from before 0.2.3.** Before 0.2.3, Certo copied its whole
  list into `~/.config/certo/`. That copy still works, but it hides
  Certo's newer values. `certo models update` reduces it to your own
  changes (see [the command](../reference/commands.md#certo-models-update)).
- **A flag or setting chooses the strategy.** A project's
  `certo-models.yaml` says whether its runs use `--auto-model` or
  `--escalate`, unless you pass a flag or set `CERTO_MODEL_SELECTION`.

## Where Certo's own list lives

In the Certo package, as `certo/data/models_list.yaml` and
`certo/data/task_profiles.yaml` (in the repository:
[src/certo/data/](../../src/certo/data/models_list.yaml)).
Don't edit the installed copy: the next release replaces it. Put your
changes in your own `models_list.yaml` instead. How the list is kept up to
date for a release is in
[CONTRIBUTING.md](../../CONTRIBUTING.md#check-certos-model-list).

## Related

- [The model files](../reference/models-yaml.md): every field, exactly
- [Pick models automatically](../guides/pick-models-automatically.md)
- [Auto-model or escalation](auto-model-or-escalation.md)
