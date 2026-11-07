# Prompt: study and improve the agent loop

The Author's prompt of 2026-11-07, kept as written for a later session
(TODO.md, "Study and improve the agent loop"). Not started.

---

Study and improve Certo’s agent loop. Start by reading `CLAUDE.md`, `TODO.md`, `ARCHITECTURE.md`, and the relevant entries in `DECISIONS.md`. Trace the current run, verification, retry, escalation, checkpoint, independent-test, and milestone flows before proposing changes.

Do not implement every idea as one large rewrite. First, give me a short, prioritized plan that names the relevant code paths, tests, risks, and any decisions you need from me. Then ask which improvement to implement first. Do not edit code until I choose.

Consider these improvement areas:

1. **Recover from regressing fix attempts.** Use existing checkpoints to detect when an agent’s repair attempt makes verification worse, and design a safe way to offer or perform rollback. Preserve the current behavior unless the user opts in or the change is supported by measurements.

2. **Protect verification quality.** Improve how Certo detects and communicates changes to tests and check configuration. Distinguish legitimate task changes from changes that weaken the evidence Certo relies on.

3. **Strengthen independent tests.** Explore ways to reduce test writers’ misunderstandings, including whether a separately selected writer model would help. Keep ambiguous or unusable test results from being treated as proof of failure.

4. **Verify applications, not just test commands.** Consider bounded smoke checks such as probing a configured HTTP endpoint or checking that a frontend renders. Do not introduce arbitrary command execution from task text or unauthenticated server requests. Follow the project’s existing security decisions and ask me before changing those boundaries.

5. **Plan larger tasks as milestones.** Explore having Certo propose milestones with measurable acceptance criteria, let the user review and approve the plan before work begins, and preserve the existing rule that later milestones start only after earlier ones are verified.

For each selected improvement:

- Read the relevant existing code, tests, TODO entries, and decisions first. Reuse existing helpers and checkpoints where appropriate.
- Ask me before making a significant behavior or safety decision that isn’t already settled.
- Make a focused change with tests for both success and failure cases. Keep existing defaults and behavior unless the approved design intentionally changes them.
- Update the matching user documentation and maintain `TODO.md`, `DECISIONS.md`, and `ARCHITECTURE.md` as required.
- Run the smallest relevant tests, then the project’s required test and lint checks.
- For changes intended to improve agent results, measure them with the benchmark on a local and a cloud model before claiming improvement. Don’t make live model calls or incur API costs without my approval.
- Don’t publish, tag, or commit changes.

Use `src/certo/starter/tasks/sky-hopper.md` as a candidate multi-milestone evaluation task; do not change the task itself unless I approve. Report what changed, test results, benchmark evidence (if approved and run), limitations, and the next open improvement.
