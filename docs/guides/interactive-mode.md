# Interactive and confirm mode

By default, Certo's agent works alone from start to finish. This guide
shows how to stay involved: the interactive session, where you give
tasks and follow-ups one message at a time; answering the agent's
questions (interactive mode); and approving every action before it runs
(confirm mode). They work only in the `certo` command, not in server
mode.

## The interactive session

In a terminal, run `certo` with no task, or `certo -i "task"` to start
with one (since 0.2.4). The session takes the whole terminal window: the
transcript at the top, starting with a header, an input box under it, and
a status line at the bottom:

```text
╭─────────────────────────────────────────────╮
│ ✓ certo 0.2.4                               │
│   the coding agent that checks its own work │
│                                             │
│   model    anthropic/claude-haiku-5-5       │
│   folder   ~/certo-projects                 │
│   /help for commands · shift+tab: switches  │
╰─────────────────────────────────────────────╯

┌──────────────────────────────────────────────────────────────────────────────┐
│>                                                                             │
└──────────────────────────────────────────────────────────────────────────────┘
 haiku-5-5 · manual · ~/certo-projects
 ask before actions: off · mode: manual · effort: default   (shift+tab, ctrl+t, ctrl+o)
```

- **A message is a task.** The run prints what `certo "task"` prints
  (the agent's work, Certo's checks, the verdict) into the transcript.
  In a Certo workspace the task gets its own project folder, as usual.
- **The next message continues it**, as `certo --resume "message"`: the
  agent gets its conversation back, and Certo checks the result again.
  `/new` makes the next message a new task.
- **Ctrl-C** stops a run after its current step; the next message
  continues it. With nothing running, it clears the input box. Ctrl-D
  (on an empty box) or `/quit` ends the session; a run still working is
  stopped first. When the session ends, the whole transcript is printed
  to the terminal, so it stays in its scrollback.
- **Scroll the transcript** with the mouse wheel or PgUp/PgDn; pressing
  Enter goes back to the end. The window keeps the last 5,000 lines; the
  transcript printed when the session ends has all of them. Up and Down in the input box bring back
  what you typed before. The session takes the mouse, so to select text
  for copying, hold Shift (Option in macOS Terminal) while you drag.
- **Under the prompt**, a status line shows the model, the mode, the
  project, the last verdict and its time, and what the session has
  spent; under it, the switches:

  ```text
   haiku-5-5 · manual · ledger · verified · 4m 12s · $0.03
   ask before actions: off · mode: manual · effort: default   (shift+tab, ctrl+t, ctrl+o)
  ```

  With `--auto-model` or `--escalate` the line shows the model that
  ended the last run, or `model per task` before the first.

  Shift+Tab turns asking before each action ([confirm mode](#confirm-mode-approve-every-action))
  on or off, Ctrl+T cycles the mode (manual, `--auto-model`,
  `--escalate`), Ctrl+O the reasoning effort. A switch changes the next
  task, never one that is running.
- **Type `/`** to see the commands, completed as you type (the table
  below).

### While a run works

The prompt stays, and the status line follows the run, about four times
a second. The model working now comes first: with `--escalate`, the
rung's model and which rung; with `--auto-model`, the model Certo chose
(and the next one, if a model fails and Certo moves on). Then the
milestone, the fix attempt and the last check run when they apply, the
agent's steps, the time, the cost so far and the last action:

```text
 ⠹ haiku-5-5 · step 7 · 17s · $0.0035 · last: terminal python -m pytest -v 2>&1; python -c "from hello im…
 ctrl+c stops · ask before actions: off · mode: manual · effort: default   (shift+tab, ctrl+t, ctrl+o)
```

```text
 ⠋ qwen3.8-27b-local · rung 1 of 6 · 11s · $0.0000
```

- **Questions come to the input box.** With asking before actions on,
  `Approve? [y/N]` replaces `>`: type the answer and press Enter. A
  command that asks, such as `/rollback`, asks there too. So do the
  questions `certo --interactive` asks about models: with
  `--auto-model`, which model to start on (Enter takes the recommended
  one, or type its number):

  ```text
  Use recommended model [qwen3.8-27b-local]? [Y/n or a number]:
  ```

  with `--escalate`, whether to try the next model before each climb;
  with `/make-milestones`, whether to run the plan, edit it first, or
  stop; in milestone mode, after each verified milestone, whether to go
  on, with a note for the next one, or stop
  ([Run in milestones](run-in-milestones.md#run-it)). The run waits for
  your answer. The agent itself doesn't stop to ask you (see
  [below](#why-the-agent-doesnt-ask-by-default)), unless you set
  `CERTO_INTERACTIVE=yes`: your next message continues the task.
- **`?` asks Certo's docs**, as `/ask`: type `?how does auto-model pick
  a model`. At the prompt, also while a run works; and at a run's
  question, where the answer comes first and the question is asked
  again. A `?` alone is an ordinary answer.
- **A message you type waits** for the run to end, then continues it.
  The status line shows it (`queued: ...`); a second message replaces
  the first. If you stop the run, the waiting message isn't sent, and
  Certo says so.
- **Commands:** `/help`, `/ask` (and `?`), `/model`, `/mode`, `/effort`, `/clear`
  and `/quit` work during a run. The others (`/verify`, `/new`,
  `/rollback`, ...) say they wait for the run to end. A command such as
  `/verify` works in the background too, with its name on the status
  line. `/clear` empties the screen; the transcript printed at the end
  still has everything.

The commands:

| Command | Does |
|---|---|
| `/help` | The commands and the keys. |
| `/new` | The next message is a new task. |
| `/resume` | Continue the last run here, as `certo --resume`. |
| `/milestones FILE` | Run a task file [milestone by milestone](run-in-milestones.md). |
| `/make-milestones [N] TASK` | Have a model [plan the milestones](run-in-milestones.md#let-certo-write-the-milestones), exactly `N` of them when given, then run them. |
| `/verify` | Check the project, with no agent (`certo verify`). |
| `/ask QUESTION` | Answer from Certo's docs (`certo ask`). `?QUESTION` does the same. |
| `/report [NOTE]` | Write the last run's problems to a file (`certo report`). |
| `/checkpoints` | List the checkpoints. |
| `/rollback N` | Go back to checkpoint `N` (asks first). |
| `/model NAME` | Use this model for the next tasks. |
| `/mode manual\|auto\|escalate` | Set the mode, as Ctrl+T. |
| `/effort default\|low\|medium\|high` | Set the effort, as Ctrl+O. |
| `/clear` | Clear the screen. |
| `/quit` | End the session (also `/exit`, Ctrl-D). |

`/verify`, `/report`, `/checkpoints` and `/rollback` work on the last
task's project. Without a terminal (a pipe, CI) or with `--json`, no
session opens: scripts keep the plain run.

## Why the agent doesn't ask by default

The agent is told that nobody is available to answer questions, so it
should decide for itself and keep working until the task is done. This is
on purpose: the tool Certo is built on can't tell a question from a final
answer. Without this rule, an agent that stops to ask "should I use SQLite
or Postgres?" would look exactly like an agent that finished.

## Interactive mode: answer the agent

Set `CERTO_INTERACTIVE=yes` in your settings, then run the task:

```bash
certo "Scaffold a FastAPI service" --project my-api
```

In a terminal, the `--interactive` flag opens the
[interactive session](#the-interactive-session) instead, where your next
message continues the task. Without a terminal, or with `--json`,
`--interactive` is the same as `CERTO_INTERACTIVE=yes`.

- The agent may stop and ask instead of guessing.
- When it stops, Certo shows its last message and asks you:

  ```text
  Your reply (Enter to finish the task):
  ```

  Type an answer to continue the same conversation, or press Enter to
  accept the work as done.
- You can go back and forth as many times as you want.
- In milestone mode, only the last milestone asks this. Every other
  milestone asks once, after its checks: go on, add a note for the next
  milestone, or stop ([Run in milestones](run-in-milestones.md#run-it)).
- At any of Certo's questions, an answer starting with `?` is a question
  for [`certo ask`](../reference/commands.md#certo-ask): Certo answers it
  from its docs and asks again.
- Time spent waiting for you doesn't count against the task's time budget.

**Only the agent's part of the task is interactive.** After you press Enter,
Certo's own checks run as usual: if a test fails, Certo sends the failure
back to the agent and lets it retry with no further questions to you.

With `--auto-model` too, Certo also shows the ranked model list and lets
you pick one. See [Pick models automatically](pick-models-automatically.md).

## Confirm mode: approve every action

Set this in your settings (there is no command-line flag):

```bash
CERTO_CONFIRM_MODE=always
```

Before every action, such as a terminal command or a file edit, Certo
shows it and waits:

```text
--- Confirmation required (CERTO_CONFIRM_MODE=always) ---
  terminal: command='rm -rf build/' is_input=False timeout=None reset=False kind='TerminalAction'
Approve? [y/N]
```

- Only `y` or `yes` approves. Anything else, including just Enter, rejects
  the action. The agent sees the rejection and can try something else.
- Approving lets exactly that one action run. The agent asks again before
  the next one.

Confirm mode is slow for long tasks, but useful when you try a new model,
a new skill, or a task on an important folder.

## In server mode

The server has no terminal to ask you, so:

- `CERTO_INTERACTIVE=yes` only removes the "work alone" rule. Nobody can
  answer, so tasks may end less complete. Leave it at `no` for
  `certo-server`.
- With `CERTO_CONFIRM_MODE=always`, the first action is rejected and the
  task stops with the verdict `confirmation_required`. Leave it at `never`
  for `certo-server`.

## Related

- [Safety](../concepts/safety.md)
- [Commands](../reference/commands.md#certo)
