# Examples

A script that runs one task with several models, one after the other, so
you can compare them, and a launcher that gives Certo's MCP server
settings of its own.

The sample tasks are not here: they are in
[`src/certo/starter/tasks/`](../src/certo/starter/tasks/), the files
`certo init` copies into a new workspace's `tasks/` folder. Any task file
works with the script.

## Compare models on the same task

`compare-models.sh.example` runs one task with every model in a list, one
after the other. Each model builds its own copy of the project, and the
script ends with a table of verdicts, times and costs. In short:

```bash
cp examples/compare-models.sh.example compare-models.sh
chmod +x compare-models.sh
# edit the model lines between the two "# ----" markers, then:
export ANTHROPIC_API_KEY=...   # one variable per provider you listed
./compare-models.sh src/certo/starter/tasks/hanoi.md
```

How to write the model lines, where the results go and how to read
them: [Compare models on one task](../docs/guides/compare-models-on-a-task.md).

## Start Certo's MCP server with its own settings

`certo-mcp-launcher.sh.example` starts `certo mcp` for one MCP client
(an editor, an agent, a service) with its own model, time budget and
folder, without changing your other Certo commands. The example uses a
model served by Ollama on another machine of your network. In short:

```bash
cp examples/certo-mcp-launcher.sh.example ~/bin/certo-mcp-local-model
chmod +x ~/bin/certo-mcp-local-model
# edit the settings between the two "# ----" markers: the folder, the
# model and where it answers, then make the folder:
mkdir -p ~/certo-mcp-workspace
~/bin/certo-mcp-local-model    # prints nothing and waits: it works (Ctrl-C)
claude mcp add certo-local-model -- ~/bin/certo-mcp-local-model
```

Every setting, how to check the model first and the JSON for other
clients: [One server with its own settings](../docs/guides/use-certo-over-mcp.md#one-server-with-its-own-settings).
