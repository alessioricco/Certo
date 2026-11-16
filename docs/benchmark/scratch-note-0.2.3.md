# Replay: the note on scratch files created in the run, Certo 0.2.3

From 0.2.3, when a failing check's output names a file the agent created
in this run and the file's name says it is scratch, the fix message says
so: if the file was only for trying things out, delete it instead of
fixing it ([How verification works](../concepts/how-verification-works.md)).
It comes from a user's milestone run: a model that took over left a
smoke script, `.milestone6-smoke.mjs`, at the project's top; the
project's lint failed on it, and the next model edited it twice instead
of deleting it. The note changes what the agent is told, so before the
release it was checked against the recorded runs and once live.

## The replay

Every conversation recorded by the benchmarks on the machine that runs
them (1,242 transcripts, Certo 0.1.13 to 0.2.3) was read again: for each
fix message Certo sent after a failed check (62), which files the note
would have named. "Created in this run" is read from the agent's file
creations in the transcript. Certo 0.2.3 at commit `9593975`, on
2026-11-16.

| Rule | Fix messages with the note | Files it named |
|---|---|---|
| First draft: any file created in the run, not a test | 11 of 62 | every time the task's own module (`ledger.py`, `src/main.rs`, `wordle_score.py`, `tokenBucket.js` ...) |
| As released: only scratch-named files the task doesn't name | 0 of 62 | none |

- **The first draft was wrong.** In a new project the real work is
  created in the run too, and the note would have told a model to delete
  its main file if it was "only for trying things out".
- **The released rule** points out only a file whose name says scratch
  (`tmp`, `temp`, `scratch`, `smoke`, `spot-check`, `try`, `trial`,
  `probe`, `playground`, `repro`, `experiment` as a word in the name, or
  a copy ending `.new`, `.bak`, `.orig`, `.old`, `.tmp`), never a test
  file, a file the task names, or one an acceptance check asks for. The
  recorded runs created such files (`smoke_tmp.py`, `edit_tmp.py`,
  `spot-check.js`, `inventory.py.new`), but no failing check named one.
- **No recorded run gets a different message.** Without a named scratch
  file the fix message is the same as before, word for word.

## The live pilot

A task made for the note, [opening-hours](tasks-0.2.3-scratch/opening-hours/task.md):
its `lint` script fails on any `console.log`, and the task suggests trying
a few dates in a quick script first. One run per arm on
`anthropic/claude-haiku-5-5`, high effort, with and without the note
(`created_note: false`), on 2026-11-16, $0.03
([bench-0.2.3-scratch-cloud.yaml](bench-0.2.3-scratch-cloud.yaml)). Both
`verified`, hidden tests passed. The note never fired: Haiku tried the
dates with `node -e` instead of a file, and ran the lint itself before
finishing.

## What it shows

The note is for the rare run that leaves a scratch file a check fails on,
like the user's milestone run; it changes nothing for the others. How
often a model then deletes the file on the first fix attempt hasn't been
measured: no benchmark run reached that point.
