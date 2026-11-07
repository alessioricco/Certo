# Examples

A script that runs one task with several models, one after the other, so
you can compare them.

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
