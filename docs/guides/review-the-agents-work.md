# Review the agent's work safely

This guide is a routine for using the agent's work without surprises:
what to set up before a run, what to read after it, and how to undo it.
It is for anyone who runs Certo on code they care about. Each step links
to the page with the details.

`verified` means the project's checks passed, and nothing more. The
checks can miss a mistake, most often when the agent wrote the tests
too: of 300 saved benchmark runs that Certo called `verified`, 8 were
still wrong ([Check files changed by benchmark runs](../benchmark/check-file-changes-0.1.24.md)).
So read the work before you keep it.

## Before the run

1. **Commit or stash first.** The agent edits files in place, and your
   git history is the safest undo. Certo warns you when the folder has
   uncommitted changes, or isn't a git repository. See
   [Work on an existing project](work-on-an-existing-project.md#commit-first-the-warning-about-uncommitted-changes).
2. **Pick how much the agent may do alone.** In local mode its commands
   run as your user, with your permissions, and nothing stops a command
   from reaching files outside the folder
   ([Safety](../concepts/safety.md#what-the-agent-can-do)). When you
   try a new model, a new skill, or a task on an important folder:
   - approve each action with `CERTO_CONFIRM_MODE=always`
     ([Interactive and confirm mode](interactive-mode.md#confirm-mode-approve-every-action));
   - or run the agent in a container with `--execution docker`
     ([Run in Docker](run-in-docker.md), experimental).
3. **Give the expected answers in the task**, so the checks test what
   you meant, not what the agent understood
   ([Write a task Certo can check](write-a-good-task.md)). For work where
   a wrong result costs more than the run, add
   [independent tests](independent-tests.md): tests written from the
   task before the agent starts.

## After the run

1. **Read the verdict and the report.** The report in
   `.certo/reports/` says why the verdict, which checks ran, and which
   files were created, modified and deleted. Certo writes it, not the
   agent. See
   [The report of each run](run-records-and-costs.md#the-report-of-each-run).
   Any verdict other than `verified` has its next step in
   [What to do after each verdict](after-the-verdict.md).
2. **Compare the files changed with what you asked.** In a git
   repository, `git status` and `git diff` show every change. A file
   you didn't expect to change is the first one to read.
3. **Read any change to the tests first.** An agent can make checks pass
   by weakening them. After a `verified` run, Certo lists each test file
   and check setting the agent changed or deleted:

   ```text
   Verification: verified
     - The agent changed 1 file the checks rely on: tests/test_calc.py (1 line changed). The checks passed on the changed files; read the changes before you trust them.
   ```

   The change may be right, if the task asked for it. Removed lines are
   the ones to read first. See
   [Verdicts](../reference/verdicts.md#changed-check-files).
4. **Read the tests the agent wrote.** Do they test what the task asked,
   with the right expected results? The agent's tests can share its
   misunderstanding.
5. **Try it yourself.** Run the program, open the page, call the API.
   Certo's checks can't use the work the way a person does.
6. **Commit**, so the next task starts from a known state.

## If you don't want the changes

- **With git:** `git restore .` and `git clean` (check with
  `git clean -n` first) put the folder back as it was at your last
  commit.
- **Without git, or to go back to the middle of a run:**
  `certo checkpoints` lists the snapshots Certo took, and
  `certo rollback N` puts the files back as they were at one of them.
  It shows the changes and asks first, and a rollback can itself be
  undone. Checkpoints leave out ignored files, environments and files
  over 10 MB. See [Go back to an earlier point](checkpoints.md).

## Related

- [Safety](../concepts/safety.md): what Certo limits and what it doesn't
- [How verification works](../concepts/how-verification-works.md)
- [Verify before every commit](verify-before-commit.md): run the same
  checks on your own changes
