---
name: cli-entry-points
triggers:
  - cli
  - command line
  - command-line
  - argparse
  - exit code
description: Make a command-line program that tests and checks can run unattended. Triggered when a task describes a command line.
---

A command-line program is checked by tests that run it with nobody
typing. So:

- Give it one entry point that takes its arguments: `main(argv)` that
  tests can call directly. In Python, the `if __name__ == "__main__":`
  block comes last in the file, after every function it uses, and only
  calls `main()`.
- Never wait for input that may not come. Read standard input only when
  the task says to, and end at the end of input: with stdin closed
  (`< /dev/null`) the program must finish, not hang.
- No prompts: every choice comes from arguments or flags. `--help`
  prints the usage and exits with code 0.
- Results go to standard output, errors to standard error, with the exit
  codes the task gives (0 on success, not 0 on an error). A user's
  mistake gets a one-line message, never a traceback.
- Test the command line itself, not only the functions behind it: run it
  with real arguments (as a subprocess, or through `main(argv)`) and
  check its output and exit code, a wrong argument included.
