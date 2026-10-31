# Manage skills

A skill is a short Markdown file of instructions, such as "how we write
pytest tests". A run gives the agent the skills that fit its task. This
guide shows which skills a run gets, and how to add your own, for every
project or for one.

## Official and third-party skills

There are two kinds, kept apart:

- **Official skills** come with Certo. A new release can change them;
  nothing else does.
- **Third-party skills** are yours: written by you, or downloaded from
  someone else. They live in one of two folders, outside any git
  repository's tracked files:

| Scope | Folder | Applies to |
|---|---|---|
| Global | `~/.config/certo/skills/` | every project on this computer |
| Project | `<project>/.certo/skills/` | one project (`.certo/` is never committed: it ignores itself) |

A project can also have **its own** skills, `.agents/skills/` and
`AGENTS.md`, which you may commit and share with other tools. Certo reads
them but never writes them (see [The project's own skills](#the-projects-own-skills)).

When two skills have the same name, the later one in this order wins:
official, global, project, the project's own. So a skill of yours can
replace an official one, for example to change `pytest-conventions`. A run
then prints a line saying so, and `certo skills list` shows it.

## See what a run gets

```bash
certo skills list
certo skills list --project hanoi
```

Each skill shows how it fires and roughly how many tokens it adds. Size
matters on a local model with a small context. To see what one task would
get, and why:

```bash
certo skills list --project demo --task "Build a snake game with pytest tests"
```

```text
For the task 'Build a snake game with pytest tests':
  From its first message (about 334 tokens):
    repository-discovery (official): "build" is in the task
    my-style (global): "game" is in the task
    pytest-conventions (project): "pytest" is in the task
  Later, maybe:
    pin-dependencies (official): if the agent touches pyproject.toml, requirements*.txt
```

The matching is the same one a run uses: whole words, any case. "tests"
does not match the trigger "test".

## Add a skill you wrote

Write the skill as a Markdown file with a short header:

```markdown
---
name: my-style
triggers:
  - game
  - snake
---

Keep functions short. Put the game logic apart from the input and output,
so it can be tested.
```

Then add it for every project, or for one:

```bash
certo skills add my-style.md --global
certo skills add my-style.md --project demo
```

`--project NAME` is a project in your projects folder, as for
`certo "task" --project NAME`. `--project .` is the current folder: the
one a run without `--project` works in.

```text
Added 'my-style' to ~/.config/certo/skills. It is on.
  Fires when the task says: game, snake; about 24 tokens.
```

Certo loads the file the way a run would before copying it, so a skill
with a broken header is refused. If the folder already has a skill with
that name, Certo asks before replacing it (`--yes` skips the question).

The header decides when the agent gets the skill:

| Header | The agent gets the skill when |
|---|---|
| `triggers: [...]` | one of the words appears in the task or the conversation (whole word, any case) |
| `paths: [...]` | it opens, creates or edits a file that matches one of the patterns with the file editor (reading the file in the terminal, or changing it with a command such as `pip install` or `npm install`, doesn't count) |
| neither | always |

A skill can also be a folder with a `SKILL.md` file, in the
[AgentSkills](https://agentskills.io/specification) format. Add the
folder the same way. Such a skill usually has no triggers: the agent sees
its name and description, and opens it when it decides it needs it.
Examples of each kind are in [Write a good skill](#write-a-good-skill).

To stop using a skill:

```bash
certo skills remove my-style --global
```

Official skills can't be removed.

## Write a good skill

A skill is part of the agent's instructions, so write it as
instructions: what to do and what never to do, in a few lines. Leave out
background the agent doesn't need to act.

- **Fire narrowly.** Choose trigger words that appear in the tasks the
  skill is for, and rarely elsewhere. A skill that fires on `add` or
  `code` fires on almost every task.
- **Words match whole and exactly.** `game` doesn't fire on "games", and
  `test` doesn't fire on "tests". List both forms when you need them:
  `triggers: [test, tests]`.
- **Keep it short.** Every skill that fires costs context. On a local
  model with a 32K context, a few large skills leave little room for the
  code. `certo skills list` shows each skill's size.
- **Check it before you rely on it.** `certo skills list --task "..."`
  shows whether a task you'd really write gets the skill:

  ```text
  For the task 'Write the tests for the snake games':
    From its first message (about 192 tokens):
      pytest-conventions (official): "tests" is in the task
      my-style (global): "snake" is in the task
  ```

  `my-style` fired on "snake", not on "games".
- **A skill guides; it doesn't check.** If something must be true, make
  it a test or a check the project runs: Certo's verdict comes from those,
  not from the skill.

Three kinds, by how they fire:

**On words in the task** (`triggers:`), shown above.

**When the agent works on certain files** (`paths:`), for rules about one
kind of file. Only the file editor counts: a file the agent reads with
`cat` or changes with a command doesn't fire the skill, so use words in
the task instead when the rule matters before the agent edits the file.
`python-deps.md`:

```markdown
---
name: python-deps
paths:
  - pyproject.toml
  - requirements*.txt
---

Pin every dependency to an exact version.
```

```text
Added 'python-deps' to ~/.config/certo/skills. It is on.
  Fires when the agent touches: pyproject.toml, requirements*.txt; about 10 tokens.
```

**When the agent asks for it** (a `SKILL.md` folder), for a longer
procedure the agent needs only sometimes. The `description` is what the
agent reads to decide, so say when to use it. `release-checklist/SKILL.md`:

```markdown
---
name: release-checklist
description: Steps to follow before tagging a release of this project.
---

1. Run the full test suite.
2. Update CHANGELOG.md.
```

The folder's name must be the skill's `name`. Other files can sit next to
`SKILL.md` (for example `scripts/`), and the skill can point the agent to
them.

A `.md` skill with no `triggers:` and no `paths:` goes into every run.
Use that only for a few lines that truly apply to every task.

## Download a skill from git

```bash
certo skills add github:anthropics/skills skills/algorithmic-art --global
certo skills enable algorithmic-art --global
```

A skill from git is treated as untrusted:

- **Downloaded is not on.** It stays off until you run `enable`. Read its
  files first.
- **Exact and checked.** The folder's `skills.lock.json` records the
  source, the exact commit, the license and a hash of every file. A skill
  whose files changed on disk is skipped; `certo skills sync` restores it.
- **Licenses.** Certo recognises a few common open licenses (MIT,
  Apache-2.0, BSD, ISC, MPL-2.0, Unlicense, CC0) from their text. Anything
  else is `unknown`, and `enable` refuses it until you add
  `--accept-unknown-license` after reading the terms. This is a text
  match, not legal advice.
- **Changes turn it off.** If `certo skills update` brings new content or a
  new license, the skill is off again until you enable it.
- Certo never runs a downloaded file, and shows a skill's `` !`command` ``
  as text. But a skill's text can still ask the agent to run its scripts.
  See [Safety](../concepts/safety.md#third-party-skills).

> **Experimental.** Downloading skills from git works and is tested, but
> no downloaded skill has been benchmarked. See
> [Experimental features](../README.md#experimental-features).

### Where to find skills

Two public repositories hold skills in the format Certo reads (a folder
with a `SKILL.md`). Licenses differ from skill to skill: `certo skills
add` shows the one it found, so read it before you enable the skill.

| Repository | Path of a skill | Example |
|---|---|---|
| [anthropics/skills](https://github.com/anthropics/skills) | `skills/NAME` | `certo skills add github:anthropics/skills skills/algorithmic-art --global` |
| [OpenHands/extensions](https://github.com/OpenHands/extensions) | `skills/NAME` | `certo skills add github:OpenHands/extensions skills/qa-changes --global` |

The OpenHands repository is the public skill catalog of OpenHands, the
agent toolkit Certo is built on. It has about 70 skills. Most connect to
a service (GitHub, GitLab, Jira, Linear, Datadog, Kubernetes and others);
a few are about the code itself, such as `code-review`,
`code-simplifier`, `security`, `qa-changes` and `iterate`.

Two things to know about the OpenHands skills:

- **Most fire on a slash command.** `qa-changes` fires when the task
  says `/qa-changes`, so write that in the task. `certo skills list`
  shows when each skill fires.
- **Their links are skipped.** Most of their folders contain
  `.claude-plugin` and `.codex-plugin`, links to plugin files for other
  tools. Certo copies a downloaded skill without its links, and says which
  ones it skipped:

  ```text
  Warning: Skipped links inside the skill (what they point to is copied on its own): .claude-plugin, .codex-plugin.
  ```

## The project's own skills

`AGENTS.md` and `.agents/skills/` at the top of a project are part of the
project: commit them, and other AI tools read them too. Certo gives them
to the agent on every task in that folder, and never changes them.
`CLAUDE.md`, `GEMINI.md` and `.cursorrules` there count the same way
(`CLAUDE.md` only for Claude models, `GEMINI.md` only for Gemini).

A project Certo generates (with `--project`, inside `CERTO_PROJECTS_DIR`)
gets only the files inside its own folder. If `CERTO_PROJECTS_DIR` sits
inside a git repository, that repository's `AGENTS.md`, `CLAUDE.md`,
`.agents/skills/` and the rest are left out: they are instructions for
that repository, not for the project.

When you run Certo on an existing folder instead, such as one package
of a larger repository, the agent also reads these files from the top of
that repository, because they describe the code it works on.

`AGENTS.md` holds facts every task should know, in plain words:

```markdown
This project uses FastAPI and Poetry.
Run the tests with `poetry run pytest`.
Never edit files under migrations/ by hand.
```

Certo can write it when it starts a task (this replaces the file, and
needs `--project`):

```bash
certo "Add a /health endpoint" --project my-api --agents-md "This project uses FastAPI and Poetry."
```

A `CLAUDE.md`, `GEMINI.md` or `.cursorrules` file works the same way.
`.agents/skills/` holds skill files, written as above. In a git
repository, the repository's top folder counts too; where both have a
skill of the same name, the folder the agent works in wins.

Because these files are in the folder the agent works in, the agent can
read and change them. Commit them, so you see any change in `git diff`.

## OpenHands plugins

OpenHands, the agent toolkit Certo is built on, also has *plugins*:
folders that can add skills, tools (MCP servers) and hooks, which are
commands run on agent events. Certo doesn't use them. OpenHands would
load them into every run on its own, so Certo checks before a run and
**doesn't start** if it finds one it would load:

- any plugin in your user folders: `~/.agents/plugins/`,
  `~/.openhands/plugins/` and the plugins installed there;
- for a project Certo generates (`--project`), a plugin in
  `.agents/plugins/` or `.openhands/plugins/` of a git repository around
  it.

A project's own `.agents/plugins/` is fine, and so is the repository's
when you run Certo on an existing folder: they belong to the code the
agent works on. Docker runs aren't checked, because the container has no
user plugins.

To use what a plugin offers, add its skills to Certo instead
(`certo skills add`), so they are listed, versioned and kept apart from
Certo's own. To run Certo, move or rename the plugin folders while you
use it. See
[Troubleshooting](../troubleshooting.md#openhands-plugins-would-be-loaded-into-this-run).

### Where to find plugins

OpenHands' public plugins are in the `plugins/` folder of
[OpenHands/extensions](https://github.com/OpenHands/extensions/tree/main/plugins),
the same repository as its skills. Most of them are a few skills plus
scripts and workflows for GitHub Actions; `city-weather` has a slash
command. None has hooks or MCP servers today.

Their skills download like any other, with the path inside the plugin:

```bash
certo skills add github:OpenHands/extensions plugins/onboarding/skills/setup-agents-md --global
```

Some plugin skills are only links to the repository's `skills/` folder
(`plugins/pr-review/skills/code-review`, for example). Download those
from `skills/NAME` instead, as in
[Where to find skills](#where-to-find-skills).

## Official skills

Eight lifecycle skills, for every language, each firing on words in the
task:

| Skill | Fires on | Covers |
|---|---|---|
| `repository-discovery` | implement, build, add, create, refactor, migrate, integrate, scaffold, inspect, explore | Find the project's real languages, tools, commands and conventions before assuming any. |
| `requirements-analysis` | feature, requirement, bug, unclear, ambiguous, vague | Pin down the outcome, acceptance criteria, edge cases, and what "verified" means here. |
| `implementation-planning` | refactor, architecture, redesign, restructure, rearchitect | Read the code first, plan the smallest change, avoid unrelated edits. |
| `testing-and-verification` | test, implement, fix, bug | Use the project's own checks, add focused tests, never weaken a test to pass. |
| `debugging-and-failure-repair` | error, fail, failing, failed, traceback, exception, crash, broken | Start from the real error, find the cause, make a small fix, run the check again. |
| `security-review` | auth, authentication, authorization, login, password, token, secret, credential, session, payment, api, database, deploy, production | Secrets, injection, access control, unsafe defaults, data leaks. |
| `documentation-and-operational-readiness` | api, config, configuration, setup, install, deploy, cli, endpoint | Keep the README, setup steps and configuration docs in step with the change. |
| `completion-and-release-readiness` | release, deploy, production, ship, launch, pull request, PR | A final review before finishing; never claim success while a check fails. |

And seven more:

- `pytest-conventions`, `commit-conventions` and `fastapi-conventions`;
- `pin-dependencies`, which fires when the agent edits `pyproject.toml`
  or `requirements*.txt`;
- `testable-interactive-apps`, which fires on interactive, game, menu,
  terminal, stdin or standard input: it keeps a game's or menu's rules
  apart from its input and output, and has the agent test both, even
  when the task doesn't ask for tests;
- `python-environment`, which fires on pip, venv, virtualenv, pypi,
  pyproject.toml, requirements.txt or third-party: dependencies are
  declared in the project's file and installed from it, into the
  project's own environment, with test tools as development
  dependencies;
- `node-project-setup`, which fires on node, node.js, nodejs, npm,
  javascript or typescript: a real `test` script, a `build` script when
  there is a build step, the lockfile kept, and scaffolders run without
  prompts.

The agent is also told to apply the lifecycle skills when they fit even if
no trigger word appears, and to skip them for trivial changes.

## Moving from the old folders

Until version 0.1.22, your skills lived in `./skills` (`CERTO_SKILLS_DIR`)
and downloaded ones in `./third_party_skills/`, both relative to the
folder `certo` runs from, where they could end up in a repository. Since
0.1.23 Certo doesn't read them, and `certo-admin skills` is gone. If you
still have skills there, add each one again:

```bash
certo skills add skills/my-style.md --global
certo skills add github:OWNER/REPO skills/NAME --global
```

Then delete the old folders, and any `CERTO_SKILLS_DIR`,
`CERTO_THIRD_PARTY_SKILLS_DIR` or `CERTO_THIRD_PARTY_SKILLS_LOCK` line
from your settings: Certo warns while one is set.

## Good to know

- **Skills guide; they don't check.** Whether the result works is still
  decided by Certo's own checks.
- **Every skill that fires costs context.** Prefer narrow triggers, and
  check with `certo skills list --task`.
- **Docker execution (experimental):** skills haven't been checked under
  `--execution docker`.

## Related

- [Commands: `certo skills`](../reference/commands.md#certo-skills)
- [Add custom tools](add-custom-tools.md)
- [Work on an existing project](work-on-an-existing-project.md)
