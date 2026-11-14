# Benchmark: trusted skills, Certo 0.2.3

From 0.2.3 a run adds the usable skills of your trusted repositories that
fit its project and task ([Trust a whole
repository](../guides/manage-skills.md#trust-a-whole-repository)). That
changes what the agent reads, so it is checked before the release
(`CLAUDE.md`, working agreement 2). The rule: the same model with
trusted skills does no worse than without them, on a cloud model and on
a local one.

This is a check for harm, not for benefit. On the 13 bundled tasks only
the 4 Node tasks get a trusted skill, and it is always the same small
one: `npm`, about 56 tokens. The other 9 tasks get none, so they are
left out. Whether bigger skills help is measured later, on tasks where
they fit (`TODO.md`, "Do trusted skills help?").

## The setup

- **Certo:** 0.2.3 from the repository (unreleased).
- **Machine running Certo:** Darwin 25.6.0, arm64, Apple M1, 8 CPUs,
  16 GB RAM.
- **Trusted repository:** `github:OpenHands/extensions`, `path: skills`,
  pinned at commit `4f91a480f747` and assessed once with
  `certo skills assess --project .`: 52 usable, 15 to review, 6
  rejected. **File:**
  [skill_sources-0.2.3-trusted.yaml](skill_sources-0.2.3-trusted.yaml).
- **Tasks:** `room-bookings`, `semver-order`, `slugify`, `token-bucket`
  (task set version 2, `6ed42dae4bca`).
- **Arms:** the same model twice, with the assessed skills folder
  (`skills_dir`) and without it. `CERTO_TRUSTED_SKILLS_TOKENS` at its
  default, 4000.
- **Cloud:** `anthropic/claude-haiku-5-5`, high effort, 5 repeats, 40
  runs, 3 at a time, on 2026-11-10 from 07:40 UTC, commit `27cb703`.
  **File:** [bench-0.2.3-trusted-cloud.yaml](bench-0.2.3-trusted-cloud.yaml).
- **Local:** `ollama/qwen3.8:27b`, thinking on, on Ollama 0.40.15 on
  another machine, a 65,536-token window, model digest `aaee06c39dcf`,
  3 repeats, 24 runs. **File:**
  [bench-0.2.3-trusted-local.yaml](bench-0.2.3-trusted-local.yaml), with
  [models_list-0.2.2-effort.yaml](models_list-0.2.2-effort.yaml) and
  [models-0.2.2-effort.yaml](models-0.2.2-effort.yaml).
  It ran in two nights. On 2026-11-10 (from 20:48, commit `6791176`) the
  Ollama machine went offline after 10 runs; the 14 runs that couldn't
  reach it were run again with `--resume` on 2026-11-11 (21:00 to 23:51,
  commit `bf240db`). The code in between changed what happens when a run
  runs out of time (the checks still run), not its verdict.
- **Results folders:** `bench-results/trusted-0.2.3-cloud` and
  `bench-results/trusted-0.2.3-local`, on the machine that ran them.

The skill reached every run of the trusted arms: Certo printed
`added the trusted skill 'npm' (github:OpenHands/extensions, about 56
tokens): the task says "npm", for node, about setup.` in 20 of 20 cloud
runs and 12 of 12 local runs, and in none of the other arm.

## Results

| Arm | Hidden tests passed | Verified | Fooled | Caught | Median time | Tokens in / out | Tool-call reminders | Cost |
|---|---|---|---|---|---|---|---|---|
| Haiku, trusted skills | 20/20 (100%) | 20/20 (100%) | 0 | 0 | 1m 00s | 9,515,019 / 347,552 | 0 | $0.3645 |
| Haiku, none | 20/20 (100%) | 20/20 (100%) | 0 | 0 | 54s | 9,794,437 / 355,943 | 0 | $0.3700 |
| qwen3.8, trusted skills | 11/12 (92%) | 9/12 (75%) | 0 | 1 | 7m 42s | 3,482,041 / 194,820 | 31 | $0 |
| qwen3.8, none | 10/12 (83%) | 9/12 (75%) | 0 | 0 | 6m 05s | 2,518,727 / 181,951 | 13 | $0 |

Hidden tests passed, per task, on qwen3.8 (Haiku passed every task in
every run):

| Task | Trusted skills | None |
|---|---|---|
| room-bookings | 3/3 | 1/3 |
| semver-order | 2/3 | 3/3 |
| slugify | 3/3 | 3/3 |
| token-bucket | 3/3 | 3/3 |

- **No worse.** Haiku is the same in both arms. On qwen3.8 the trusted
  arm passed one more run (11 against 10) and verified as many (9).
  With 12 runs an arm, that difference is chance.
- **The failed trusted run** (`semver-order`, round 3) ended `stuck`
  after 7 minutes: the agent read `package.json` again and again until
  the stuck check stopped it. Nothing in this run shows whether the
  skill caused it.
- **The reminders** come mostly from one run each. With trusted skills,
  22 of the 31 were in one run (`room-bookings`, round 1): the agent kept
  writing a file edit as text. It ended `inconclusive` (its tests didn't
  run), but the hidden tests passed. Without, 7 and 6 were in two runs,
  both verified.
- **More tokens on qwen3.8**, about 960,000 more, nearly all on
  `room-bookings`, where the trusted runs went on longer and did better.
  The skill itself is about 56 tokens.
- **Not verified, hidden tests passed:** 3 of the 6 local runs that
  weren't verified had right work. Five of the 6 were `room-bookings`,
  the largest task, where 4 runs hit the 30-minute budget (3 of them
  without trusted skills).

## What this shows

Adding a fitting trusted skill to a run does no harm here, on a cloud
model and on a local one. So trusted skills can ship on, at the
default budget.

## What this doesn't show

Whether trusted skills help. Only one skill fired, a small one, on 4
small tasks; the larger skills in the repository (about 4,200 tokens
each) never fit these tasks. That needs tasks a large skill fits, on a
local and a cloud model.
