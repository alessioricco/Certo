# Merge YAML settings files

Write `yamlmerge.py`, a Python module that is also a command-line
program, which merges YAML settings files. Read and write YAML with the
PyYAML package from PyPI; don't write a YAML parser of your own. Add
pytest tests.

## The module

- `merge(*docs)` returns a new mapping that merges the mappings given,
  left to right, without changing them:
  - a key that is a mapping in both is merged the same way, at any depth;
  - otherwise the later value replaces the earlier one, whatever its
    type: a list replaces a list (lists are never joined), and `null`
    (`None`) replaces a value too.
  - `merge()` with no mappings returns `{}`.
- `load_and_merge(paths)` reads each file with `yaml.safe_load` and
  merges them in order. An empty file counts as `{}`. A file whose top
  level isn't a mapping raises `ValueError`, with the file's path in the
  message.

## The program

`python yamlmerge.py FILE...` prints the merged settings to standard
output as YAML, written with `yaml.safe_dump(result, sort_keys=True,
default_flow_style=False)`, and exits with code 0.

- No file named: a usage line on standard error, exit code 2.
- A file that is missing, isn't valid YAML, or whose top level isn't a
  mapping: one line on standard error naming the file, nothing on
  standard output, exit code 1.
