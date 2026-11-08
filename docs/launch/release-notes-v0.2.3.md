# Certo v0.2.3

Not released yet.

This release keeps the agent in its project, lets runs use skills from
repositories you trust, and makes bigger, milestone-by-milestone builds
easier to start:

- **A task gets its own project folder.** In a Certo workspace, a task
  run without `--project` gets `projects/<name>`, named after the task.
- **The agent stays in its project root.** It is told its root, and
  Certo blocks an action that reaches outside it.
- **Trusted skill repositories.** List the repositories you trust in
  `skill_sources.yaml`; `certo skills assess` checks and classifies every
  skill in them; a run adds the ones that fit its project and task, and
  `certo skills suggest` shows which.
- **A task file written in milestones runs in milestones** without
  `--milestones`; `--no-milestones` sends it as one task.
- **Three bigger samples, in milestones**: a platform game with
  parallax, a 3D wireframe tank game, and a team task board web app with
  SQLite.
- **`--auto-model` chooses per milestone**, by the milestone's own
  title first, and the example task profiles gain `build`, for apps,
  games and features.
- **The example model list, checked again** (2026-11-07): `cost`
  now follows the price to one decimal, five models re-rated, four new
  ones, Kimi K2.7 Code out. **`certo models check`** compares your list's
  prices and cost ratings with LiteLLM's price list, and `--fix` sets
  each cost from its price.
- **Estimates from your own runs.** Every run is recorded in
  `run_stats.csv`; the benchmark plan, the escalation prompt and
  `certo check --task` estimate a model's cost and time from its last
  runs instead of a fixed guess, and `certo check` says how far off the
  estimates were.
- **`certo init` offers more models.** After a passing model check, it
  asks whether to set up more models now, and on yes runs
  `certo init models` at once.
- **`certo check` gives an Ollama model's real speed**, in tokens a
  second, as Ollama measures it.
- **A guide to check another AI tool's work** with `certo verify`.

## New: the agent stays in its project root

Run from a Certo workspace (the folder `certo init` makes, with
`projects/` in it) without `--project`, a task used to get the whole
workspace as its folder. The agent then chose a subfolder itself, read
the other projects, and Certo's checks found several projects and ended
`stuck`. Now:

- **A task gets its own project folder**, named after the task file, its
  title or its first words, and Certo says which before the run:

  ```text
  Project: projects/farewell, named after the task. The agent works only in that folder.
  ```

  A folder that already exists isn't reused: the new task gets
  `farewell-2`, and `--project farewell` works on the old one. In any
  other folder (your own repository, say) Certo works where you run it,
  as before. `certo init` now also creates the empty `projects/` folder,
  so this works from the first run.
- **The agent is told its project root**, and that nothing above or
  beside it is part of the task.
- **Certo blocks an action that reaches outside the root** before it
  runs: the file editor outside the root, or a command like `ls ..`,
  `cat ../other/file` or `cd ~`. The agent is told why and carries on:

  ```text
  Certo blocked an action outside the project root: <workspace>/projects is outside the project root <workspace>/projects/farewell-3. Work only inside the project root: nothing outside it is part of the task.
  ```

  The run summary counts them (`Blocked outside the project root: 2
  actions`), and so do the JSON result and each benchmark run
  (`blocked_outside_root`). It is a guard rail, not a sandbox;
  `--execution docker` is the sandbox. Three live runs are in
  [The project root in 0.2.3](../benchmark/project-root-0.2.3.md).

Measured on Claude Haiku 5.5, the 13 bundled tasks, 3 repeats per arm:
with the root sentence, the agent tried to reach outside its root in 2 of
39 runs, against 9 of 39 without it (the blocked actions of that run,
checked again with the final guard), with every hidden test passing in
both arms and about 11% fewer input tokens. The same comparison on a
local model is still to run.

See [Safety](../concepts/safety.md#what-the-agent-can-do) and
[`certo`](../reference/commands.md#certo).

## New: trusted skill repositories

Instead of adding skills one by one, list the git repositories you trust
in `skill_sources.yaml` (`~/.config/certo/` for every project, or
`<project>/.certo/` for one), then run:

```bash
certo skills assess --global
```

Certo downloads each repository at an exact commit and checks every skill
in it with the same rules as `certo skills add`: license, scripts, size,
how it fires. Each skill is classified (testing, review, setup...;
python, node...) by fixed rules, with no model call, and gets a verdict:
`usable`, `needs review` or `rejected`. On `OpenHands/extensions`, 73
skills: 52 usable, 15 to review, 6 rejected.

A run then adds the usable skills that fit its project and task, whole,
up to `CERTO_TRUSTED_SKILLS_TOKENS` (default 4000; `0` turns them off),
and says which before it starts:

```text
Certo: added the trusted skill 'uv' (github:OpenHands/extensions, about 591 tokens): the task says "uv", for python.
```

A skill fits when its own trigger fires on the task, or when two links
tie it to the work (a project file it names, the project's ecosystem, a
step the task names), so a Node skill doesn't fit every Node project.
Official skills, yours and the project's own win over a trusted skill of
the same name. `certo skills suggest` shows the same choice before a
run, with the reasons, and installs nothing:

```bash
certo skills suggest --project my-api --task "Set up uv and add pytest tests"
```

Experimental: no benchmark yet shows whether these skills help. See
[Trust a whole repository](../guides/manage-skills.md#trust-a-whole-repository).
Getting started now says what the built-in skills are, and how to add
your own or a trusted repository.

## New: milestones without the flag, and three bigger samples

A task file written in milestones (two or more `## Milestone N`
headings, numbered 1, 2, 3...) now runs milestone by milestone without
`--milestones`. Before, it was sent as one task, and its acceptance
blocks reached the agent as plain text and were never checked. Certo
says so before it starts:

```text
Certo: tasks/team-board.md is written in 5 milestones, so it runs milestone by milestone (--no-milestones runs it as one task).
```

`--no-milestones` sends such a file as one task, as before. A file with
milestone headings that can't be read as milestones (a broken acceptance
block, say) is refused before any model call. Text, URLs and files with
a single heading run as one task, as before.

`certo init` puts three bigger samples in `tasks/`, each written in 4 or
5 milestones. They aren't in the menu at the end of `init`. Their first
runs, on Claude Haiku 5.5, verified every milestone, for $0.34 to $1.11
each ([the record](../benchmark/milestone-samples-0.2.3.md)):

- `sky-hopper.md`: a side-scrolling platform game with a camera and
  three parallax layers, in the browser;
- `iron-horizon.md`: a first-person 3D tank game in wireframe, with its
  own 3D drawing and no library, in the browser;
- `team-board.md`: a team task board web app in Python: accounts and
  sessions, projects with roles, columns and drag-and-drop cards,
  comments, history and search, on a SQLite database.

```bash
certo tasks/team-board.md --project team-board
```

See [Run a task in milestones](../guides/run-in-milestones.md).

## New: `--auto-model` chooses per milestone, and a `build` profile

`--auto-model` picks a task profile from trigger words in the task's
title. In a task written in milestones every milestone was matched by
the task's title, so all of them got the same profile. Now each
milestone is classified by its own title first: in a game whose title
matches `build`, a milestone called "Fix the flaky tests" is
`debugging`, and goes to the models that profile ranks first. A
milestone whose title has no trigger word falls back to the task's
title, as before. Only titles are read, never the text under them.

The example `task_profiles.yaml` has a new profile, `build` (build,
implement, app, application, game, website, feature), which weighs code
and cost. Before, an app or a game usually matched no profile and got
`default`, which weighs cost most. Copy the new profile into your own
`task_profiles.yaml` to use it: Certo never changes your copy.

`certo check --task` shows, for a task file written in milestones, each
milestone's profile and first model:

```text
It runs milestone by milestone. Each milestone is classified by its own title first, then by the task's:
  1. The level and the camera: build ("game" in the task's title), claude-haiku-5-5 first
  2. Running and jumping: build ("game" in the task's title), claude-haiku-5-5 first
```

`MODEL_DECISIONS.md` keeps every milestone's choices, each under its own
`## Milestone N of M: title` section. Before, each milestone's run
rewrote the file, so only the last milestone's choice was left.

See [Pick models automatically](../guides/pick-models-automatically.md#how-a-model-is-chosen).

## Changed: the example model list, checked again

Every model in `models_list.yaml.example` was checked against its
provider's pages and the public leaderboards on 2026-11-07.

**`cost` follows the price, to one decimal.** It was a band: every model
between $3 and $10 per 1M tokens (blended, 3 input to 1 output) got 2,
so Opus 5.5 rated as cheap as Sonnet 5.5 at twice the price. Now
`cost = 4 − log2(price) / 2`, kept between 1 and 4.9 (5 is for local
models): each doubling of the price takes half a point. Sonnet 5.5 is
3.0, Opus 5.5 2.5, Fable 5.1 1.8, Haiku 5.5 and GPT-6 Luna 4.9. A test
checks every rating against the price in the model's description.

**Re-rated:**

- GPT-6.1 Sol: code 4 → 5 (Terminal-Bench 4.0 58.2% on the public
  leaderboard, level with GPT-6 Astra).
- Claude Fable 5.1: reasoning and precision 5 → 4. Artificial Analysis
  scores it 50, Opus 5.5 59, and Opus 5.5 leads on every benchmark both
  report, at less than half the price. A FrontierMath number in its
  description had no source and is gone.
- DeepSeek Flash: code 3 → 4, now served by V4.1-Flash (Terminal-Bench
  4.0 42.3%, vendor-reported).
- Gemma 4 31B (both tags): code 1 → 2. The weak agentic numbers in its
  description had no source; it passed 26 of 27 hidden tests in Certo's
  own baseline.

**New:** GPT-6.1 Terra ($1 / $5, Terminal-Bench 4.0 50.3%), Kimi K3.1
Pro ($2 / $10, Terminal-Bench 4.0 65.7%, vendor), and two local models,
Nemotron 3.5 Lightning (fast, weak at coding) and Flint 40B
(vendor-reported only, to measure).

**Out:** Kimi K2.7 Code, closed to new users and retiring by the end of
2026. Its `certo init` preset is now Kimi K3.1 Pro.

**Descriptions:** Gemini 4 Argon is generally available and works
through LiteLLM's normal path (the warning is gone); its price rises to
$4 / $20 on 1 Dec, and it is rated at that price. GPT-5.6 Sol's
promotion ends on 30 Nov. GPT-4.1 and GPT-4.1 mini retire on 14 Jan
2027. Llama 3 has no tool calling in Ollama, so it can't run Certo's
agent. Artificial Analysis changed its index scale in October; the
numbers are now on the new one.

**`certo models check`** keeps your own list honest the same way. It
compares every model's price with the price list of the installed
LiteLLM, with no network and no key, and reports an id LiteLLM doesn't
know, a price that differs and a `cost` that isn't what its price gives.
`--fix` sets those costs; a price that differs is for you to settle with
the provider's pricing page. See
[`certo models check`](../reference/commands.md#certo-models-check).

With these ratings, `--auto-model` puts Opus 5.5 first for debugging and
research, and Haiku 5.5 first for builds, with GPT-6.1 Sol and Sonnet
5.5 next. Your own `models_list.yaml` is never changed:
`certo models update` brings it up to date and keeps your changes.

## New: estimates from your own runs

Cost estimates were a fixed guess: every run priced at about 500k input
and 20k output tokens at list price. Most input is cached, so the guess
was far off: the 0.1.15 baseline's plan said ~$14.54, and the runs cost
$1.22.

Now every finished run adds a line per model to `run_stats.csv` in your
Certo folder (`~/.config/certo/`): the model, the kind of run (`task`,
`milestone`, `bench`), the task profile, the verdict, the time, the
tokens, the cost, and the estimate it had. Model ids and numbers only.
With 3 or more runs of a model of the same kind, an estimate is the
median of its last 20, with the range:

- the benchmark plan: `~$0.03 per run, measured over 3 runs, ~45s each`;
- the escalation prompt: `roughly $0.05 for a run, the median of your last 12`;
- `certo check --task`: `Measured for gpt-luna: ~$0.02 per run ($0.01-$0.05), ~1m 00s (30s-1m 30s), from your last 3 task runs with profile debugging.`

`certo check` also says how far the estimates given before runs were
from the real cost: `Cost estimates, last 20 runs: actual 0.4x the
estimate (the 20 before: 0.1x).` See
[Measured runs](../guides/run-records-and-costs.md#measured-runs).

## New: `certo init` offers more models

`certo init` sets up one model. Setting up more of them, with keys for
other providers, and choosing `--auto-model` or `--escalate` for every
run, was a separate command, `certo init models`, which the setup never
named. Now, when the model check passed and the settings are for all
projects, `certo init` asks:

```text
Set up more models now?
▸  1. No, one model is enough for now
   2. Yes: add models and keys, then choose how Certo uses them
```

The default is No: one model is all you need to start. Yes runs
`certo init models` in the same session, starting from the model you
just saved. Under "Next", `certo init` now also lists
`certo init models`, so you can do it later. See
[`certo init`](../reference/commands.md#certo-init).

## New: an Ollama model's real speed in `certo check`

`certo check` timed the whole test request, loading the model included,
so it couldn't tell how fast a local model writes. It now asks Ollama for
one short answer and reports Ollama's own measure:

```text
Ollama 0.40.6 · context window 131,072 tokens (from server) · 2.0s
Speed: 37.8 tokens a second (64 tokens written in 1.7s, measured by Ollama).
```

A few tokens a second usually means part of the model runs on the CPU;
see [Troubleshooting](../troubleshooting.md#every-step-is-very-slow).
Cloud models print nothing new.

## Also

- **Check another AI tool's work:** a new guide shows `certo verify`
  after Claude Code, Cursor, Aider or your own edits, and what each
  verdict says about the tool's "done" (issue #31). See
  [Check another AI tool's work](../guides/verify-another-tools-work.md).
- **`certo --help` lists every subcommand** (`init`, `check`, `models`,
  `skills` and the others) in a section of its own, like the options.
- **Troubleshooting:** `pip` from a Python older than 3.12 finds no
  Certo; the page shows how to install it with uv, which brings its own
  Python.
- **Benchmarks:** an arm can leave out the project-root sentence
  (`root_prompt: false`), to measure what it changes.
- **One home for the sample tasks:** `src/certo/starter/tasks/`, the
  files `certo init` copies. Older drafts in the repository's `examples/`
  folder are gone; it now holds only the script that compares models on
  one task.
- **`--auto-model`'s fallback, described as it works.** When a model's
  work fails Certo's checks, the next model in the ranking takes over
  and makes the fix attempt; the first model doesn't get one first.
  `MODEL_DECISIONS.md`, the terminal notice, `certo check --task` and the
  docs said "when a fix attempt still fails". The next model is the next
  best fit for the task, not a stronger one; for that, use `--escalate`
  (see [Pick models automatically](../guides/pick-models-automatically.md#limits)).
- **Claude on Anthropic's newer API version:** version 2026-10-21
  refuses `temperature`, `top_p` and `top_k`. Certo sends none of them to
  Claude, at any reasoning effort, so runs keep working when the tools
  Certo builds on move to that version.
