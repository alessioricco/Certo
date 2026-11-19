# Use Certo's MCP server on another machine

`certo mcp` talks over stdio only: the client starts it and reads its
output. To run it on another machine, for example the one with the GPU
that runs your local model, let SSH carry that stdio. The client on your
computer starts `ssh`, and `ssh` starts `certo mcp` on the other
machine. SSH does the login, so nothing new listens on the network.

This guide sets up an SSH key that can **only** start `certo mcp`: it
can't open a shell, run another command or forward a port. In the
examples the other machine is `gpu-box.local` and your user there is
`you`; use your own names.

## What you need

- On the other machine: an SSH server (OpenSSH 7.2 or later, for
  `restrict`), and Certo installed for your user, not as root:
  `uv tool install certo` puts it in `~/.local/bin/certo`.
- On your computer: an MCP client, such as Claude Code, and `ssh`.

## 1. On the other machine: Certo's settings

The server reads its model and keys from the user settings file there,
`~/.config/certo/.env`. With Ollama on the same machine:

```dotenv
CERTO_LLM_MODEL=ollama/qwen3.8:27b
CERTO_LLM_BASE_URL=http://localhost:11434
```

Check it with `certo check`. Then make the folder the tools may work
in, for example `mkdir ~/certo-workspace`.

## 2. On your computer: a key for Certo only

```bash
ssh-keygen -t ed25519 -f ~/.ssh/certo_remote -N "" -C certo-mcp
cat ~/.ssh/certo_remote.pub
```

Use a new key, not your usual one: the next step limits what this key
can do, and your usual key should keep working as before.

## 3. On the other machine: allow that key one command

Add one line to `~/.ssh/authorized_keys` of your user, by hand (not
with `ssh-copy-id`, which adds the key with no limits). The line is
the options, then the whole content of `certo_remote.pub`:

```text
restrict,command="env PATH=/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin CERTO_PROJECTS_DIR=/home/you/certo-workspace/projects /home/you/.local/bin/certo mcp --root /home/you/certo-workspace" ssh-ed25519 AAAA... certo-mcp
```

- `command="..."`: whatever the client asks for, this key runs only
  this command.
- `restrict`: no terminal, no port, agent or X11 forwarding.
- `env PATH=...`: a forced command doesn't read your shell profile, and
  Certo and the agent need `uv`, `git` and `python` on the `PATH`.
- `--root`: the folder the tools may work in, with every folder inside
  it.
- `CERTO_PROJECTS_DIR`: the tools may also work in Certo's projects
  folder (`~/projects` by default). Setting it inside the root keeps
  the server in one folder.

Keep the line on one line, with plain `"` quotes: an editor that
changes them to curly quotes, or splits the line, makes SSH skip it.
`ssh-keygen -lf ~/.ssh/authorized_keys` should list the key with the
fingerprint that `ssh-keygen -lf ~/.ssh/certo_remote.pub` shows on your
computer.

## 4. On your computer: a name for the connection

Add to `~/.ssh/config`:

```text
Host certo-remote
  HostName gpu-box.local
  User you
  IdentityFile ~/.ssh/certo_remote
  IdentitiesOnly yes
```

`User` is your user name on the other machine, which may differ from
the one on your computer.

## 5. Add it to the client

The command is just `ssh -T certo-remote`: the other machine decides
what runs. `-T` asks for no terminal, which keeps the stream clean.

**Claude Code:**

```bash
claude mcp add certo-remote -- ssh -T certo-remote
```

**Any other client:**

```json
{
  "mcpServers": {
    "certo-remote": {
      "command": "ssh",
      "args": ["-T", "certo-remote"]
    }
  }
}
```

## Check it

Ask the client for Certo's tools, or call `list_projects`: the paths it
shows are the other machine's. A folder outside the root is refused,
as on your own computer:

```text
Error executing tool verify: /etc is outside the folders this server may use: /home/you/certo-workspace/projects, /home/you/certo-workspace
```

To see that the key is limited, ask it for another command:
`ssh -T certo-remote whoami` doesn't print your name; the other machine
starts `certo mcp` instead, which waits for a client (press Ctrl-C).

## If it doesn't connect

- **`Permission denied (publickey,password)`**: check `User` in
  `~/.ssh/config` first. Then, on the other machine, the permissions:
  your home folder not writable by others, `~/.ssh` `700`,
  `authorized_keys` `600`. `sudo journalctl -u ssh -n 20` (on systemd
  machines) says why SSH refused the key.
- **`--root ... is not a folder`**: the folder in the `command="..."`
  line doesn't exist on the other machine.
- **The client says the server closed at once**: run
  `ssh -T certo-remote` in a terminal. An error from Certo, such as a
  missing setting, shows up there.

## Good to know

- **What the key allows.** It starts `certo mcp`, nothing else. Inside
  the root, though, a run's agent runs commands as your user, as every
  Certo run does: it installs packages and runs tests. For a stricter
  limit, put the key on a separate user with no admin rights.
- **Everything is on the other machine.** Projects, task files and
  `--root` are paths there; the agent works there, not on your
  computer.
- **A dropped connection ends the server**, and a run still going stops
  with it, as when a client closes. Its state is in the project's
  `.certo/` folder, so `run_resume` continues it.
- **The model and the agent share that machine.** The agent's installs
  and test runs add to the load of a local model. Watch its
  temperature on long runs.

## Related

- [Use Certo over MCP](use-certo-over-mcp.md): the tools, `--root` and
  what a run returns.
- [Configuration](../reference/configuration.md): the settings file
  and `CERTO_PROJECTS_DIR`.
