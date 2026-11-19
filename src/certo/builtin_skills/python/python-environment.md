---
name: python-environment
triggers:
  - pip
  - venv
  - virtualenv
  - pypi
  - pyproject.toml
  - requirements.txt
  - third-party
  - poetry
  - uv add
  - uv sync
description: Install a Python project's dependencies from its own files into its own environment, so the checks and the README work for the next person. Triggered when a task mentions pip, a virtual environment or the dependency files.
---

When a Python project needs packages:

- Use the project's own environment: the terminal already points at it.
  Never install into another interpreter, with `--user` or with `sudo`,
  and don't make a second environment next to it or delete it.
- Declare each dependency in the project's file first (`pyproject.toml`,
  or `requirements.txt` when the project uses one), then install from
  that file, not package by package: `pip install -e .`, `pip install -r
  requirements.txt`, or `uv sync` for a project with `uv.lock`. A package
  installed by hand and not declared is missing on the next machine.
- Give each new dependency a version range (`"fastapi>=0.110,<1.0"`,
  not a bare `"fastapi"`): with none, the next install can pull in a
  new major version that breaks the project. `pip install X` and
  `uv add X` in the terminal count too: declare the range in the file.
- Put test-only tools such as `pytest` in the project's development
  dependencies (`[project.optional-dependencies] dev` or
  `[dependency-groups] dev`), not in the runtime ones.
- Run tests as `python -m pytest` from the project root, so the
  project's own interpreter and packages are used.
- When an install fails, read the error: a wrong package name or a
  version that doesn't exist won't be fixed by trying again.
