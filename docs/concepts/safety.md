# Safety

An agent that runs commands on your computer can do damage. This page
explains what Certo limits, what it doesn't, and how to reduce the risk:
budgets, confirm mode, where the agent may work, secrets, server mode and
third-party skills.

## What the agent can do

In local mode (the default), the agent's terminal runs commands **as your
user**, with your permissions, in the task's folder. Nothing stops a
command from reading or changing files elsewhere. Treat a task like
running a script you haven't read.

To reduce the risk:

- commit before a task, so you can roll back (Certo warns you when you
  can't; see [Work on an existing project](../guides/work-on-an-existing-project.md));
- run in a container with `--execution docker`
  (see [Run in Docker](../guides/run-in-docker.md));
- approve every action with confirm mode (below).

## Budgets

Three limits stop a task that goes wrong:

| Limit | Setting | Default |
|---|---|---|
| Steps in one agent run | `CERTO_MAX_ITERATIONS` | 50 |
| Fix attempts after a failed check | `CERTO_MAX_VERIFY_RETRIES` | 2 |
| Time for the whole task, all runs together | `CERTO_MAX_TASK_SECONDS` | 1800 (30 minutes) |

The step limit applies to each run separately, and a task can have
several runs (the first one, then retries). The time budget covers all of
them. When it runs out, the agent stops after its current step, so one
very slow step can go a little past it. A terminal command can't ask to
wait longer than the time left. When it runs out, the verdict is `budget_exhausted`, unless the
agent's last step went past it and the checks then pass: work that passes
is `verified`. Time spent
waiting for your answer in interactive mode doesn't count.

## Confirm mode

`CERTO_CONFIRM_MODE=always` shows every action before it runs and waits for
`y`. Anything else rejects it. In server mode there is nobody to ask, so
the first action is rejected and the task stops with
`confirmation_required`. Certo never approves an action on its own. See
[Interactive and confirm mode](../guides/interactive-mode.md).

## Where the agent may work

- `--project NAME` (and the server's `project` field) must be a relative
  name with no `..`, and the resolved folder, following symlinks, must stay
  inside `CERTO_PROJECTS_DIR`. A name like `/etc/cron.d` or `../other` is
  rejected before anything is created.
- Acceptance check paths follow the same rule, inside the task's folder.
- `--agents-md` needs `--project`, so it can't write into whatever folder
  you happen to be in.
- In a Certo workspace (a folder with `projects/`, as `certo init` makes),
  a task without `--project` gets its own `projects/<name>` folder, named
  after the task, so the agent never starts in the folder that holds
  every project.

These rules decide which folder the agent *starts* in. They don't stop its
commands from going elsewhere; see "What the agent can do".

## Certo's own environment

Certo never installs anything into the environment it runs from, and
never runs a project's code with its own Python. Each Python project gets
its own environment. The agent's terminal can't reach Certo's interpreter:
Certo removes its own folder from the terminal's `PATH`.

## Secrets

- `certo init` takes the API key at a hidden prompt, writes it with
  permissions `600` on macOS and Linux, and has no `--api-key` flag, so
  the key stays out of your shell history. It can also refer to a variable
  you already export, instead of copying the key. On Windows, the settings
  file inherits its folder's access permissions; Certo does not set a Windows
  ACL. Keep that folder accessible only to your own account.
- `certo check` shows the key only as `set` or `not set`. `certo-admin
  check-llm` removes the key from any error text it prints.
- Keeping the key in the user settings file, not in each project's `.env`,
  keeps it out of project repositories.
- `certo "<task>" --api-key ...` does put the key in your shell history.
  Prefer a variable.
- `models.yaml` holds keys too. Keep it out of git. `models_list.yaml`,
  `task_profiles.yaml` and `escalation.yaml` hold no keys or addresses, so
  they can be shared.
- Run records (`CERTO_ARTIFACTS_DIR`) contain the whole transcript: your
  task, the agent's commands and their output. They don't contain your API
  key, but they may contain anything the agent printed.
- The `.certo/` folder in each project holds the last run's conversation
  for `certo --resume`. Same as run records: no API key, but anything the
  agent printed. Git ignores it; delete it when you no longer need it.

## Server mode

`certo-server` has **no authentication**. Anyone who can reach it can send
a task, which means running commands on the machine as the user running
the server. It listens on `127.0.0.1` by default. Keep it there, or put it
behind a gateway that checks callers. For the same reason, acceptance
checks have no "run this command" kind.

## Third-party skills

A skill is text that becomes part of the agent's instructions. A skill
written by someone else is untrusted input. A skill downloaded with
`certo skills add github:...` is handled carefully:

- **Downloaded is not on.** A new skill does nothing until you enable it.
- **Licenses.** Only a few common open licenses are recognised. Anything
  else is `unknown` and can't be enabled without
  `--accept-unknown-license`.
- **Integrity.** The lockfile records the exact commit and a hash of every
  file. Every time an agent starts, Certo checks again: a skill that is
  disabled, has changed files, or has an unaccepted unknown license is
  skipped. A downloaded folder with no lockfile entry is never loaded.
  `update` disables a skill again if its content or license changed.
- **Only regular files are copied.** A link inside the skill's folder
  is skipped (what it points to is copied on its own, and Certo names the
  skipped links). A link that leads outside the folder stops the
  download.
- **Nothing is executed by Certo.** Downloaded files lose their executable
  permission. A skill's `.mcp.json` is ignored, so it can't start a server.
  Inline shell snippets (`` !`command` ``), which the agent framework would
  otherwise run when the skill is opened, are turned into plain text.
- **The text can still ask.** An enabled skill can tell the agent to run
  its scripts, using the agent's normal tools. Read a skill before
  enabling it, and consider confirm mode while you try it.

**OpenHands plugins are refused.** A plugin can add skills, tools and
hooks (commands run on agent events), and the agent framework would load
the ones in your user folders, or in a repository around a generated
project, into every run. Certo checks before a run and doesn't start if
it finds one. See [OpenHands plugins](../guides/manage-skills.md#openhands-plugins).

A skill you add from a file or folder is on at once: you chose it. Its
`.mcp.json` is still ignored and its inline snippets still turned into
text, as for a downloaded one. Third-party skills live in
`~/.config/certo/skills/` or the project's `.certo/skills/`, never in a
folder git tracks. Official skills, which come with Certo, are used as
they are.

## Related

- [Review the agent's work safely](../guides/review-the-agents-work.md): a routine before and after each run
- [Configuration](../reference/configuration.md)
- [How verification works](how-verification-works.md)
