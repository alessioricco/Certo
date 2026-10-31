# Benchmark: the python-environment and node-project-setup skills on a cloud model, Certo 0.1.27

Certo 0.1.27 adds two official skills: `python-environment` (declare a
project's packages in its own files and install from them, test tools
as development dependencies) and `node-project-setup` (a real `test`
script, the lockfile kept, scaffolders without prompts). Do they help,
and do they make anything worse? These runs answer the second question
for a cloud model, and set up the first for a local one.

## The setup

- **Certo:** 0.1.27 (not released yet).
- **Model:** `anthropic/claude-haiku-5-5`, 3 runs at a time.
- **Arms:** each run with the skills and without them (`skills_off`).
- **Three runs, all on 2026-10-31:**
  1. The four bundled Node tasks (`slugify`, `semver-order`,
     `room-bookings`, `token-bucket`, task set version 2), 3 repeats.
     **File:** [bench-0.1.27-node-skill-cloud.yaml](bench-0.1.27-node-skill-cloud.yaml).
     First run at 09:36 UTC with `node-project-setup` triggered by the
     path `package.json`, on three of the tasks; again at 10:08 UTC with
     it triggered by words in the task, on all four.
  2. Two tasks made to show what the skills are for (task set
     `skills-3`), 5 repeats, at 10:18 UTC:
     - `word-tally-node`: a Node.js program in an empty folder; the task
       asks for tests but never mentions `package.json` or `npm test`,
       so a run is `verified` only if the agent adds a real `test` script;
     - `yaml-merge`: a Python program that needs PyYAML from PyPI.
     **File:** [bench-0.1.27-setup-skills-cloud.yaml](bench-0.1.27-setup-skills-cloud.yaml).
- **Results folders:** `bench-results/node-skill-cloud-0.1.27-path-trigger`,
  `bench-results/node-skill-cloud-0.1.27` and
  `bench-results/setup-skills-cloud-0.1.27`, on the machine that ran them.

## Results

**The bundled Node tasks:**

| Run | Arm | Skill text sent | Hidden tests passed | Verified | Median time | Cost |
|---|---|---|---|---|---|---|
| Path trigger (3 tasks × 3) | without | 0/9 | 9/9 | 9/9 | 59s | $0.1719 |
| | with | **0/9** | 9/9 | 9/9 | 56s | $0.1948 |
| Word trigger (4 tasks × 3) | without | 0/12 | 12/12 | 12/12 | 67s | $0.2205 |
| | with | 12/12 | 12/12 | 12/12 | 54s | $0.2129 |

**The two skill tasks (5 repeats each):**

| Task | Arm | Hidden tests passed | Verified | What the project declares |
|---|---|---|---|---|
| `word-tally-node` | without | 5/5 | 5/5 | `test` script `node --test` 3 times, `node --test test/tally.test.js` 2 times |
| | with | 5/5 | 5/5 | `test` script `node --test` 5 times |
| `yaml-merge` | without | 5/5 | 5/5 | PyYAML in `requirements.txt` 5 times, pytest next to it 5 times |
| | with | 5/5 | 5/5 | PyYAML 5 times; pytest apart, in `requirements-dev.txt`, 4 times, and left out of `pyproject.toml`'s dependencies once |

Without the skills the two arms cost $0.1829, with them $0.1748 (median
90s and 82s per run). Every `yaml-merge` project passed its hidden tests
again in a fresh environment built only from its own files
(`scripts/fresh_env_grade.py`), with the skills and without.

## What the results say

- **A skill triggered by a path fired in none of 9 runs.** A `paths:`
  skill reaches the agent only when the file editor opens, creates or
  edits a matching file. Here the agent read `package.json` with `cat`
  and never edited it: the starter already had a working `test` script.
  `npm init` and `npm install` change `package.json` from the terminal
  too, so a path trigger misses exactly the moments this skill is for.
  It now fires on words in the task (node, node.js, nodejs, npm,
  javascript, typescript), and did in 12 of 12 runs.
- **On Haiku, neither skill made anything worse,** and neither had
  anything to fix: Haiku declared PyYAML and gave the Node project a
  real `test` script in every run, with the skills or without them. The
  only visible effect is the one the skill asks for: with
  `python-environment`, pytest went into the development dependencies
  instead of next to PyYAML.
- **Whether they help a weaker model is still open.** `qwen3.8` is the
  next run of the same file with a local model, once the Ollama machine
  is free.
- **One hidden test was stricter than the task text** in the first
  grading: it gave `word-tally-node` two files without a final newline,
  which a program that joins its files as they are reads as one word
  across the files. Fixed in the hidden test (files now end with a
  newline), and the runs graded again; the table shows the new grades
  (the results folder's `results.md` keeps the first ones).
  Before the fix, 7 of 10 runs were graded failed by that test alone.

## Related

- [Manage skills](../guides/manage-skills.md)
- [The testable-interactive-apps skill, measured the same way](interactive-0.1.26.md)
- [The benchmark guide](../guides/benchmark.md)
