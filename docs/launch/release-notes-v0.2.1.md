# Certo v0.2.1

Not released yet.

## Changed: a turn that ends on a sentence of plans is sent back

Some local models end their turn with a sentence that only says what
they will do next ("Now let me add the `save` and `load` methods"), and
no tool call, so the run stopped with the work half done. Certo now
tells the agent to make that call, or to say the task is done, as it
does for a tool call written as text, within the same
`CERTO_TOOL_CALL_REMINDERS` limit. In the saved benchmark runs this
ending appeared 4 times, all on local models, and the check finds none
of the 210 cloud endings. In
[the benchmark](../benchmark/next-step-0.2.1.md), on the expenses task
in milestones, no run ended this way: `qwen3.8:27b` was verified in 5
of 5 runs and Haiku in 3 of 3, but the reminder was never sent, so
that score is not its doing. See
[Troubleshooting](../troubleshooting.md#the-run-ends-on-a-sentence-of-plans).
