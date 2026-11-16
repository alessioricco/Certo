# The interactive session (design, 0.2.4)

The Author's request (2026-11-16): an interactive interface laid out as
the common coding-agent terminals are (Claude Code, OpenCode, Copilot
CLI): a header with the logo and the run's facts at the top, an input
box, a last line with information and switches, and Certo's commands
typed with `/`. Choices made with the Author on 2026-11-16:

- **How it opens:** `certo` with no task, in a terminal, opens the
  session in the current folder; `certo -i "task"` (`--interactive`)
  opens it and starts that task. `certo "task"` without `-i` stays the
  plain run that scripts and CI use. Without a terminal (a pipe, CI,
  `--json`), nothing changes: `certo` alone prints the usage error, and
  `--interactive` keeps its plain prompts.
- **Inline, not full-screen** (superseded the same day: the Author asked
  for full screen, as the other agent terminals have; the transcript is
  printed to the terminal on exit, and the mouse is captured):
  the transcript scrolls in the terminal and
  stays in its scrollback after the session ends; the input box and the
  status line stay at the bottom while you type. Built on
  `prompt_toolkit`, already a Certo dependency (the `certo init` menus):
  no new library.
- **Switches on the last line:** ask before actions (confirm mode),
  model mode (manual, `--auto-model`, `--escalate`) and reasoning effort.

## The screen

```text
  ╭──────────────────────────────────────────────╮
  │ ✓ certo 0.2.4                                │
  │   the coding agent that checks its own work  │
  │                                              │
  │   model    anthropic/claude-haiku-5-5        │
  │   folder   ~/certo-projects                  │
  │   /help for commands · shift+tab: switches   │
  ╰──────────────────────────────────────────────╯

 > Build a ledger CLI with pytest tests
   ... the run's output, as a plain run prints it ...
 Verification: verified

 > _
  haiku-5-5 · manual · ledger · verified · 4m 12s · $0.03
  ask before actions: off · mode: manual · effort: default   (shift+tab, ctrl+t, ctrl+o)
```

- **Header**, printed once: the logo line, the version, the model the
  next task would use (or how to set one up), the folder, and the two
  hints.
- **Input:** one line, `> `; typing `/` lists the commands with a line
  each, completing as you type. Enter sends; Ctrl-D or `/quit` ends.
- **Status line** (prompt_toolkit's bottom toolbar), below the input:
  the model, the mode, the project, the last verdict, its time, and the
  session's total cost; under it, the switches and their keys.
- **During a run** (changed the same day, after the first version): the
  run works in a thread and prints above the prompt, which stays. The
  status line follows the run live: the model working now first (a
  ladder's rung and its number, `--auto-model`'s choice, the Author
  asked for it), then the milestone, fix attempt, last checks, steps,
  time, cost and last action. The run's questions are asked at the
  prompt; a typed message waits for the run and continues it; commands
  that start no run (`/help`, `/ask`, `/model`, `/mode`, `/effort`,
  `/clear`, `/quit`) work, the others wait. Ctrl-C stops the run after
  its current step and drops a waiting message.

## What a message does

- The first message is a new task. In a Certo workspace it gets its own
  project folder, named after it, as `certo "task"` does.
- A later message continues that task (as `certo --resume "message"` in
  its project): the agent gets its conversation back, and Certo checks
  the result again.
- `/new` starts a new task with the next message.

## The commands

| Command | Does |
|---|---|
| `/help` | The commands and the keys. |
| `/new` | The next message is a new task. |
| `/resume` | Continue the last run here, as `certo --resume`. |
| `/milestones FILE` | Run a task file milestone by milestone. |
| `/make-milestones TASK` | Plan the task in milestones, then run them. |
| `/verify` | Check the project, no agent (`certo verify`). |
| `/ask QUESTION` | Answer from Certo's docs (`certo ask`). |
| `/report [NOTE]` | Write the last run's problems to a file (`certo report`). |
| `/checkpoints` | List the checkpoints. |
| `/rollback N` | Go back to checkpoint N (asks first). |
| `/model NAME` | Use this model for the next tasks (a `models.yaml` name or a LiteLLM id). |
| `/mode manual\|auto\|escalate` | The model mode, as the switch. |
| `/effort default\|low\|medium\|high` | The reasoning effort, as the switch. |
| `/clear` | Clear the screen. |
| `/quit` | End the session (also `/exit`, Ctrl-D). |

## The switches

| Key | Switch | Values |
|---|---|---|
| Shift+Tab | ask before actions | off, on (`CERTO_CONFIRM_MODE=always`) |
| Ctrl+T | mode | manual, auto (`--auto-model`), escalate (`--escalate`) |
| Ctrl+O | effort | default, low, medium, high (`--reasoning-effort`) |

A switch changes the next task, never one that is running. (Ctrl+E
would have been the obvious key for effort, but terminals use it for
"end of line".)

## Tests

The session's logic (what a message or a command runs, the status line,
the switches) is plain functions tested without a terminal; the input
loop is tested with prompt_toolkit's pipe input and dummy output.
