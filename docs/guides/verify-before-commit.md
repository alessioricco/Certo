# Verify before every commit

`certo verify` runs the same checks Certo runs after an agent finishes:
project detection, the project's environment, then its tests, build, lint
and type checks, with no model, no API key and no retries. Run it before
each commit and a broken commit never reaches git.

This guide shows how to wire that into a git hook. What `certo verify`
runs for each language, its output and its exit codes are in
[Verify in CI](verify-in-ci.md).

## The plain git hook

Save this as `.git/hooks/pre-commit` in your project (or in a shared
hooks directory) and make it executable with `chmod +x
.git/hooks/pre-commit`:

```bash
#!/bin/sh
certo verify --require-verification
```

The hook runs in the project root, which is what `certo verify` checks by
default. A nonzero exit blocks the commit.

## Exit codes

`--require-verification` makes every non-`verified` verdict fail, which
is what you want before a commit: a project with nothing to check should
not pass silently.

| Verdict | Exit code |
|---|---|
| `verified` | 0 |
| `inconclusive`, `failed`, `timed_out` | 1 |

`inconclusive` means nothing could be checked: no tests yet, an unknown
project type, or a missing tool. Add `--require-verification` so it also
blocks the commit, or leave it off if you only want real failures to
block.

## The pre-commit framework

If your project uses the [pre-commit](https://pre-commit.com) framework,
add a local hook to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: certo-verify
        name: certo verify
        entry: certo verify --require-verification
        language: system
        pass_filenames: false
```

`language: system` uses the `certo` already installed on your machine;
pre-commit does not install it for you.

## Skipping the hook

Skip the hook for one commit with:

```bash
git commit --no-verify
```

Use it deliberately, for example for a commit that only touches
documentation. A full verification run can be slow on a project with a
large test suite, which is the usual reason to skip it; a skipped check is
not a passed check.
