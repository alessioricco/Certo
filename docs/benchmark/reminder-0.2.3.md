# Benchmark: the reminder for a made-up tool result, Certo 0.2.3

In the [project-root benchmark](root-0.2.3.md), `qwen3.8:27b` once
answered with the invented result of a command, as JSON, instead of
running it: `{"command": "ls -la ...", "is_error": false, "output":
"total 16..."}`. Certo didn't recognise that as a tool call written as
text, sent no reminder, and the run ended after 31 seconds with no code.
From 0.2.3 such a message gets the tool-call reminder
(`CERTO_TOOL_CALL_REMINDERS`). That changes local runs, so it is
measured before the release (`CLAUDE.md`, working agreement 2). The
rule: the score is no worse than the root benchmark's.

## The setup

- **Certo:** 0.2.3 from the repository (unreleased), commit `a970636`.
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Tasks:** the 13 bundled tasks (task set version 2, `6ed42dae4bca`).
- **Model:** `ollama/qwen3.8:27b` with thinking on, on Ollama on another
  machine, a 65,536-token window, model digest `aaee06c39dcf`. The
  Ollama version was 0.40.15; the root benchmark ran on 0.40.6.
- **Arm:** one, the same model, settings and repeats as the root
  benchmark's arm with the root sentence (today's default), 2 repeats,
  26 runs, on the night of 2026-11-09, 21:32 to 03:17 UTC.
  **Files:** [bench-0.2.3-reminder-local.yaml](bench-0.2.3-reminder-local.yaml),
  [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml),
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml).
- **Results folder:** `bench-results/reminder-0.2.3-local`, on the
  machine that ran it.

## Before the change

A replay of the new check over every saved benchmark transcript (1,084
transcripts, 2,213 messages where the agent wrote text instead of a tool
call) found one message it now answers that it didn't before: the
31-second run above. No other message, so no false alarms.

## Results

| Run | Hidden tests passed | Verified | Fooled | Caught | Median time | Tokens in / out | Tool-call reminders |
|---|---|---|---|---|---|---|---|
| This run (with the change) | 23/26 (88%) | 21/26 (81%) | 0 | 1 | 8m 50s | 6,198,567 / 375,719 | 4 |
| Root benchmark, same arm | 20/26 (77%) | 19/26 (73%) | 0 | 3 | 7m 19s | 6,650,007 / 426,394 | 5 |
| Root benchmark, without the root sentence | 23/26 (88%) | 22/26 (85%) | 0 | 2 | 6m 35s | 6,628,147 / 413,930 | 13 |

- **No worse.** 23 of 26, within the range of last night's two arms.
- **The new reminder wasn't needed.** No message in the 26 runs was a
  made-up result. All 4 reminders were for tool calls written as text in
  the shape Certo already knew, all in one run (library-loans, round 2),
  which used them up and ended after 75 seconds, `inconclusive`.
- **The other 4 runs that weren't verified** ran out of the 30-minute
  budget. On 2 of them the hidden tests passed anyway (ledger-transfers
  and library-loans, round 1): the work was right but unfinished in
  Certo's eyes.

## What this shows

The change doesn't make qwen3.8 worse, and in saved transcripts it
answers only the message it was made for. This run doesn't show it
saving a run, because the made-up result didn't happen again: it is
rare (1 message in 2,213).

## What this doesn't show

One model, 13 small tasks, 2 repeats, and a newer Ollama than the run
it is compared with.
