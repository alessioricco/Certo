# Skills for developing Certo

The Claude Code skills and commands used to work on this repository. They
help the coding session that changes Certo; they are not part of Certo.

Certo's own skills, the ones it gives its agent, are something else: they
ship in `src/certo/builtin_skills/` and users manage theirs with
`certo skills` (see [Manage skills](docs/guides/manage-skills.md)).

## Project commands (in git)

In `.claude/commands/`, available to everyone who clones the repo:

| Command | What it does |
|---|---|
| `/verify-sdk TOPIC` | Checks an OpenHands SDK class or function against the live docs and examples before code relies on it, and reports the confirmed usage. Changes no file. |
| `/add-tool DESCRIPTION` | Adds a custom tool: Action, Observation and Executor in `src/certo/custom_tools/`, registered in `tools.py`, with a test that needs no model or network. |
| `/next-milestone [N]` | Works on the next unfinished milestone of `docs/history/SPEC.md`, then stops and reports. |

## Skills from Anthropic (downloaded, git-ignored)

From [`anthropics/skills`](https://github.com/anthropics/skills), at a
pinned commit, into `.claude/skills/`:

```bash
uv run python scripts/fetch_claude_skills.py
```

| Skill | License | Why Certo uses it |
|---|---|---|
| `skill-creator` | Apache-2.0 | Writing, testing and improving Certo's built-in skills (`SKILL.md` folders). |
| `webapp-testing` | Apache-2.0 | Testing a local web app in a browser with Playwright: web benchmark tasks such as `room-bookings`, and run-the-app verification. |

Planned: `mcp-builder` (Apache-2.0), when work on the MCP server starts.
It is listed, commented out, in the script.

## Adding or updating a skill

1. Add the skill's folder name to `SKILLS` in
   `scripts/fetch_claude_skills.py`, or change `COMMIT` to update them
   all.
2. Add or update its row here, with its license and why Certo needs it.
3. Run the script and check that the skill does what you expect.

Add a skill only when current work needs it. Skills are never copied into
the repository: only the script and this page are in git.
