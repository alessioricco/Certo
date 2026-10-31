# Live check: the `unchanged` verdict, Certo 0.1.27

Certo 0.1.14 added the `unchanged` verdict: a run whose checks pass but
which changed no file in the project folder is not `verified`, because
the checks passed before the run too. It was unit-tested but had not
been seen in a live run. These two runs show it.

## The setup

- **Certo:** 0.1.27 (not released yet), 2026-10-31.
- **Model:** `anthropic/claude-haiku-5-5`.
- **Project:** three files whose test already passes.

  `calc.py`:

  ```python
  def add(a, b):
      return a + b
  ```

  `test_calc.py`:

  ```python
  from calc import add


  def test_add():
      assert add(2, 3) == 5
  ```

  `pyproject.toml`:

  ```toml
  [project]
  name = "calc"
  version = "0.1.0"
  requires-python = ">=3.12"

  [dependency-groups]
  dev = ["pytest"]
  ```

- **Task:** `Check whether this project's tests pass and tell me the
  result. Don't change any file.` A task that needs no change, so the
  agent has no reason to edit anything.

## Results

| Run | Verdict | Exit code | Cost |
|---|---|---|---|
| `certo --model anthropic/claude-haiku-5-5 "<task>"` | `unchanged` | 0 | $0.0032 |
| The same with `--require-verification` | `unchanged` | 1 | $0.0013 |

In the first run the tests passed and the agent changed nothing, so
Certo asked once:

```
Certo: the agent changed no file in the project folder, so the passing checks say nothing about this task. Asking it once to do the task or say why no change is needed.
```

The agent answered that no change was needed (`pytest` reports
`1 passed`) and still changed nothing, so the run ended:

```
Certo verification: the agent still changed no file. The checks pass, as they did before it started, so this is reported as unchanged, not verified.
Verification: unchanged
```

## What the results say

- **The verdict works as [documented](../reference/verdicts.md#unchanged-in-more-detail):**
  one follow-up, then `unchanged` instead of `verified`, exit code 0,
  and 1 with `--require-verification`.
- **Not reproduced:** the run that found the problem (`qwen3.8` doing
  nothing on `inventory-fix` in 0.1.13). These runs show the verdict,
  not that a weaker model now does the task.

## Related

- [Verdicts](../reference/verdicts.md)
