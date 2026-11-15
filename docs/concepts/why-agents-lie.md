# Why agents lie

Coding agents don't lie on purpose. But they often say "done" when the work
is not done, and explain failures they never looked at. This page tells
the real cases we met while building Certo: what the agent claimed, what
was actually true, and what Certo does about it now. Each one changed how
Certo works.

Some fixes are hard checks: Certo runs something itself, and the agent
can't talk its way past it. Others are only instructions in the agent's
prompt, which a model can still ignore. Each story says which.

## 1. "Let me know if you have specific preferences!"

**What happened.** We gave the agent a real, multi-step task: build a
booking website. It made a plan, read a skill, and then replied: "Let me
know if you have specific preferences!" No file was written.

**Why.** For the agent framework Certo is built on, any plain text reply
ends the run, exactly like the agent saying "finished". A question looks
the same as a final answer. Nobody was there to answer, so the run simply
ended.

**Then it got subtler.** After we told the agent never to wait for
answers, it built one of the six items on its own to-do list (a demo
component), declared success, and presented the other five (booking logic,
the backend, mobile layout, tests) as "next steps for you".

**What Certo does now.**

- *Instruction:* every agent is told that nobody can answer questions,
  that it must finish its own to-do list, and that it must not turn
  required work into suggestions.
- *Hard check:* after the agent stops, Certo reads the agent's to-do list
  itself. If items are still open, it sends them back and asks the agent
  to finish. We tested this by asking an agent to create two tasks,
  finish one and leave the other open. It did, and said "done". Certo
  caught it, and the agent then finished the second task. If items stay
  open anyway, the project's checks decide, and a pass is reported as
  maybe unfinished: passing tests for one part out of six don't prove the
  other five. (Until 0.2.3 the verdict was `incomplete`, without running
  the checks; a run whose every check passed then moved to costlier
  models over one item left marked "in progress".)
- If you want the agent to ask you things, use
  [interactive mode](../guides/interactive-mode.md).

## 2. The scaffolding tool that silently did nothing

**What happened.** Asked to start a React project, the agent ran
`npm create vite@latest ...`. That tool asks questions in the terminal.
With nobody to answer, it gave up and created nothing, but its output even
printed the fix: run it again with `--no-interactive`. The agent didn't
notice. It ran the exact same command again, and again, until we stopped
it by hand: more than 200,000 tokens and $0.35 spent on a command that
never worked.

**What was true.** Nothing had been created, and the command's own output
said why.

**What Certo does now.**

- *Instruction only:* the agent is told to use each tool's
  non-interactive or CI options, to check what a command actually did
  instead of trusting its exit code, and not to repeat a command that
  visibly did nothing. A model can still ignore this.
- Certo's own checks run with no input at all, so a check that waits for
  input fails at once instead of hanging.
- The time budget (30 minutes by default) puts a ceiling on how much a
  loop like this can cost.

## 3. The invented diagnosis

**What happened.** Asked for a Tower of Hanoi game, the agent finished
with: "there are errors in the tests that need further debugging,
particularly around sequence handling and state transitions within the
game logic."

**What was true.** The file didn't even run. `hanoi.py` had an
`IndentationError`: the body of `main()` was empty, and its code had been
pasted at the bottom of another function. Every test failed before it
started. Nothing was wrong with "sequence handling". The agent never ran
the tests again before writing its summary; the explanation was made up.

This was the turning point. The model wasn't just ignoring an
instruction. It was confidently wrong about its own work, and no prompt
can fix that.

**What Certo does now.**

- *Hard check:* when the agent stops, Certo runs the project's tests
  itself, with no AI involved. On a failure it sends the **real** error
  output back to the agent and lets it try again (twice by default). If the
  checks still fail, the verdict is `retry_exhausted`, and Certo adds its
  own note, so the agent's optimistic last message is never the final word.
- *Instruction:* the agent is also told to run the tests before it
  finishes. Helpful, but not trusted.

## 4. "Set up successfully, and the development server is running"

**What happened.** Asked to build a kitesurfing booking site with Vite and
React, the agent said: "The kite surfing booking website has been set up
successfully and the development server is running."

**What was true.** The page didn't render at all. `App.tsx` had a parse
error: two JSX elements side by side with no wrapper. At the time, Certo's
check only knew pytest. On this project pytest found no tests, which is
correctly "nothing to check" for a Python project, and so the broken site
passed.

**What Certo does now.**

- *Hard check:* Certo detects the project type and runs that ecosystem's
  own checks. For a Node project with a `build` script, it runs
  `npm run build`, which fails on exactly this error. Go, Rust and Java are
  covered too. See [Verification by language](../reference/verification-by-language.md).
- "Nothing to check" is never a pass. It is its own verdict,
  `inconclusive`, with a note that says what was found.

## 5. Nothing to check is not the same as working

This one was not found in a live run. We looked for it on purpose after
story 4.

**The problem.** Two kinds of silence looked the same as success. A
project whose checks couldn't run at all (for example, `npm` wasn't
installed) looked like a clean pass. And when the agent framework's own
loop detection stopped a run as stuck, or a run ended in an error, Certo
didn't look at that, so it looked like a normal finish.

**What Certo does now.**

- *Hard check:* every check ends as `passed`, `failed`, `skipped`,
  `unavailable` (should be checkable, but the tool is missing) or
  `timed_out`. A missing tool is a limitation that is shown, not a pass and
  not a failure.
- *Hard check:* Certo reads the run's final state before verifying and
  after every retry. A stuck or failed run gets the verdict `stuck`.

## 6. The right code, the wrong test, and the words that stopped meaning anything

**What happened.** In another Tower of Hanoi run, a test kept failing. The
agent changed a comparison in `move_disk` from `<=` to `<`, ran the tests,
saw the same failure, and changed it again. Its explanations got longer
and emptier. By the second retry it wrote things like "Condition Energy
Evaluation" and "retro-verifying conditionally determined returns from
contradictory game states violations circumspect inherently making sense
of failed revisions": fluent English that said nothing.

**What was true.** The code was right. The *test* was wrong: it expected a
move to be illegal ("larger disk on a smaller one"), but at that point the
disk being moved was the smallest one, onto an empty peg, which is a legal
move. The test output showed the real state of the pegs on every attempt.
The agent never used it to question the test. Its edits couldn't change
anything: the line it edited is never reached when the target peg is
empty.

The framework's loop detection didn't notice, because it only catches
*exact* repetition, and each attempt had a different edit and different
words.

**What Certo does now.**

- *Hard check:* after each fix attempt, Certo compares the new check output
  with the previous one (ignoring timings such as `in 3.85s`). If the same
  check fails with the same exit code and the same output, the attempt
  provably changed nothing. Certo stops at once with the verdict
  `no_progress`, instead of spending more retries. It never tries to judge
  whether the agent's words make sense; it only looks at what the checks
  print.
- *Instruction:* the built-in testing and debugging skills tell the agent
  to prove a test wrong against the state it actually printed before
  editing working code a second time.

## 7. Every test passed, and the game crashed on "solve"

**What happened.** An agent wrote a Tower of Hanoi game with a menu. Every
unit test passed. Certo reported `verified`. The game crashed the moment a
player chose `SOLVE`:

```text
NameError: name 'solve' is not defined
```

**What was true.** `hanoi.py` ended like this:

```python
if __name__ == "__main__":
    main()          # main() calls solve() when the player picks SOLVE


def solve(...):     # defined after the block that runs the program
    ...
```

When you run `python hanoi.py`, Python executes the file from top to
bottom. It reaches `main()` before it has seen `def solve`, so `solve`
doesn't exist yet. The tests did `from hanoi import solve`. Importing a
file runs all of it, but skips the `__main__` block, so by the time a test
called `solve()`, it existed. The tests could never see this bug. Only a
user could.

**What Certo does now.** Two hard checks for every Python program with a
`__main__` block:

- **Entry-point order:** Certo reads the file's structure and fails if a
  function or class is defined after the `__main__` block. This is the
  check that catches this exact bug, and it names the problem.
- **Start-up run:** Certo runs `python <file>` with no input. It catches
  programs that crash on start. It can't reach a menu choice like `SOLVE`,
  because nobody types anything; that is why the order check exists.

We re-ran this as a live end-to-end test: a project with the bug, a real
agent and the real model. pytest passed, Certo's order check failed, sent
the precise diagnosis back, and the agent fixed it on the first retry.

## 8. Certo's own checks only worked on the developer's machine

**What happened.** This time the confident one was Certo. A user installed
Certo 0.1.0 with `uv tool install certo`, used a local model
(`ollama/qwen3-coder:30b`), and asked for "hello.py that prints hello,
plus a pytest test for it". Certo ran pytest with **its own** Python
interpreter. In the developer's environment that interpreter had pytest;
in a real install it didn't.

The agent then tried to install pytest into Certo's own environment. That
failed only because the environment had no pip. Then it started changing
the code to work around the problem, and the run ended with `no_progress`.
The project was fine all along.

**What was true.** The bug was invisible from the development environment,
where pytest is always installed. Our own test suite ran there too, so it
couldn't see it either.

**What Certo does now.**

- *Hard rule:* each Python project gets its own environment (an existing
  `uv.lock` project or `.venv`, or a new `.venv`). The agent's terminal and
  Certo's checks both use it. Certo installs pytest into that environment
  when the project has tests, and never runs or installs anything with its
  own interpreter.
- *Release check:* before every release, a script installs the built
  package exactly like a user does (`uv tool install`, in a throwaway
  folder) and runs `certo verify` on sample projects, including one whose
  dependency exists only in the project's own `.venv`.

## What these stories have in common

The agent's own report is a claim, not evidence. In every case the truth
was available: a test output, a file that didn't parse, a command that
printed its own fix. What was missing was someone who actually looked.

So Certo looks. It runs the checks itself, compares real output, and keeps
its verdict separate from the agent's words. And where a rule is only a
prompt instruction, the docs say so.

How the checks fit together: [How verification works](how-verification-works.md).
