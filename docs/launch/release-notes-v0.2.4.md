# Certo v0.2.4

Not released yet.

This release lets Certo split a big task into milestones itself,
answers questions about Certo from its own docs, and makes it easier to
tell Certo's maintainers what went wrong:

- **An interactive session**: `certo` alone opens it, laid out as
  coding-agent terminals are, with a header, `/` commands, follow-up
  messages that continue the task, and a status line with switches.
- **`--make-milestones`**: a model splits a task written in one piece
  into milestones, saved in the project for you to read and edit, and
  Certo runs them one at a time, each checked before the next.
- **`certo ask "<question>"`** answers from the docs of your Certo's
  own version, with a link to each section it used, and says when the
  docs don't cover something.
- **`certo report`** writes the last run's problems to one file, with
  keys hidden, to attach to a GitHub issue.
- **The run report lists Certo's notices**, and so does `certo --json`
  (a new `notices` field).

## New: the interactive session

In a terminal, `certo` with no task (or `certo -i "task"`) opens a
session. A header shows the version, the model and the folder; each
message you type is a task, and the next ones continue it, with the
agent's conversation, until `/new`. Type `/` for the commands: `/verify`,
`/ask`, `/report`, `/rollback`, `/make-milestones` and more. Under the
prompt, a status line shows the model, the mode, the project, the last
verdict, its time and what the session spent, with three switches:
Shift+Tab asks before each action, Ctrl+T cycles manual, `--auto-model`
and `--escalate`, Ctrl+O the reasoning effort. It stays in the terminal
(no full screen), and needs no new library. While a run works, the
prompt stays: the status line follows it live (the model working now,
with the rung on a ladder or `--auto-model`'s choice, the steps, time,
cost and last action), the run's questions are answered at the prompt,
a message typed meanwhile waits for the run, and Ctrl-C stops it. Scripts are unaffected:
without a terminal, or with `--json`, `certo` runs as before. See
[The interactive session](../guides/interactive-mode.md#the-interactive-session).

## New: Certo writes the milestones

Milestone mode runs a big task one checked piece at a time, but you had
to write the milestones. Now `certo --make-milestones task.md` asks a
model for them first. It writes only the milestones (a title, what to
build, how to tell it is done); Certo saves your task as you wrote it
followed by them, as `.certo/milestones.md`, so no requirement is lost,
and runs it. From a real run on Haiku:

```text
Planning milestones with anthropic/claude-haiku-5-5 (the run's model)...
Plan: 4 milestones, written by anthropic/claude-haiku-5-5 in 8s, $0.0008. Saved as /home/me/certo-projects/projects/ledger/.certo/milestones.md
  1. Project setup and add command
  2. List expenses
  3. Total
  4. CSV export
```

With `--interactive`, Certo asks before the first milestone: run it,
edit the file first, or stop. A task small enough for one go stays one
task. The model is `CERTO_PLANNER_MODEL` when set; with `--auto-model`
or `--escalate`, the first model of a new `planning` task profile
(`reasoning` 4 or more, least costly first); else the run's own.
Experimental: not yet benchmarked against hand-written milestones. See
[Let Certo write the milestones](../guides/run-in-milestones.md#let-certo-write-the-milestones).

## New: `certo ask`

Ask about Certo in your own words, and get the answer from the docs of
your own version, with a link to each section it used:

```text
$ certo ask "My task gets stopped after half an hour. How do I give it longer?"
Set a longer time budget with `--max-time MINUTES` for one run [1]. The default budget is 1800 seconds (30 minutes) [1]. ...
```

When the docs don't answer, it says so instead of guessing. Installed,
it downloads the version's docs once (a new `docs.zip` on each GitHub
Release) and works offline afterwards; only your question goes to the
model (`CERTO_ASK_MODEL`, else your configured one). On 30 test
questions Haiku answered all right, made nothing up, for $0.03 in all
([the record](../benchmark/ask-0.2.4.md)).

Over MCP, the new `search_docs` and `read_docs` tools give an editor's
agent the same docs, with no model call by Certo.

## New: `certo report`

When a run goes wrong in a way Certo should handle better, the facts
were spread over `.certo/` (`run.json`, `STATUS.md`, `RUNS.md`, the run
report, the saved conversation) and the terminal's scrollback. Now, in
the project folder:

```text
$ certo report --note "It stopped halfway; the model server was busy."
Report: /home/me/certo-projects/projects/ledger/.certo/certo-report.md
Read it before you share it: it holds the task and the checks' output.
```

The file has your Certo, Python and system; the run's task, model,
effort, time budget, step limit and how it ended; the errors the SDK
recorded (a provider timeout, a tool error, a rejected action); and the
run's report, with the checks' output, the files changed, the check
files the agent edited, the cost and Certo's notices. Every value that
looks like a key, from your settings files, `models.yaml` or by its
shape, is replaced with `[hidden]`. It calls no model and sends nothing.
See [Share a run's problems](../guides/run-records-and-costs.md#share-a-runs-problems).

## Also

- **Certo's notices are kept.** The run report gets a "Certo's notices"
  section (a blocked action, a limit coming up, failing checks sent
  back), and the JSON result a `notices` list. They used to be only on
  the screen.
- **Certo's own model list is no longer called an example.** Since
  0.2.3 every run reads it, with Certo's task profiles, as the lowest
  layer; they now live in the package as `certo/data/models_list.yaml`
  and `certo/data/task_profiles.yaml`. Nothing changes for you: your
  own files still hold only your exceptions. `models.yaml.example`,
  `escalation.yaml.example` and `bench.yaml.example` stay examples to
  copy. Pages that still said `certo init models` copies the list and
  the profiles are corrected: it hasn't since 0.2.3.

