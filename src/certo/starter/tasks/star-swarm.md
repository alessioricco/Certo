# Star Swarm: a fixed-shooter game in the browser, at production quality

Needs Node 18 or newer. A bigger sample, in milestones, and the most
open one: the agent chooses the tech stack itself in the first
milestone. Run it with

```bash
certo --milestones tasks/star-swarm.md --project star-swarm --max-steps 150
```

You are a senior game developer and technical lead. Build an original
fixed-shooter arcade game in the formation-shooter genre (enemies in a
formation, dive-bomb attacks, capture and power-up mechanics), running in
the browser and shipped at production quality.

## Hard constraints

- Original name, art, sound and enemy designs. No names, sprites, music
  or assets from any existing game. "Star Swarm" is only this file's
  name: the game's name is yours to choose.
- JavaScript-based (TypeScript allowed), running in the browser on
  desktop and mobile.
- The tech stack is your decision, made in milestone M0. Nothing is
  decided in advance.
- Fixed-timestep game loop, deterministic and seedable random numbers.
- Zero-cost assets only: procedural or vector art you create, sounds
  generated with WebAudio, or properly licensed free assets (record the
  licenses).
- Clean architecture: engine, game logic, rendering, audio, input and UI
  kept separate. No global state.
- Any dependency has a permissive license (MIT, Apache or BSD), is
  actively maintained, and is justified in writing.
- Keyboard, gamepad and touch input.

## Rules for every milestone

- `package.json` defines the scripts `test` (unit tests, no browser
  needed), `lint` and `build`, plus `typecheck` if you choose
  TypeScript, whatever the stack. These are the checks run after each
  milestone, so they must exist from M0 and pass at the end of every
  milestone. End-to-end browser tests, if you add them, go in a separate
  script such as `test:e2e`.
- Each milestone leaves the game in a working, playable state (for M0 and
  M1, a working page), and keeps every earlier milestone working.
- At the end of each milestone: update `PLAN.md`, add a `## Mn — title`
  section to `CHANGELOG.md` (what was done and how to check it by hand),
  and record in `DECISIONS.md` why you chose things. A requirement that
  is ambiguous gets a sensible default, recorded in `DECISIONS.md`.
- Definition of done, every milestone: build with zero errors and
  warnings; lint and tests pass; playable at 60 FPS on a mid-range
  laptop; no console errors; the three documents updated; manual
  verification steps written in the changelog.

## M0 — Plan, tech stack and foundations

Research and decide. For each decision below, compare at least two or
three options against production readiness, performance on mid-range
phones, bundle size, learning and maintenance cost, testability,
long-term maintainability, and support for a shippable v1.0. Make a
clear recommendation with reasoning, and say what would change your mind.

1. Libraries or none: for example plain Canvas 2D, PixiJS, Phaser,
   Kaboom or Excalibur, Three.js, or your own code. Cover rendering,
   audio (WebAudio or a library), input, and physics or collision.
2. Language: JavaScript or TypeScript.
3. Project setup: a Node.js toolchain (Vite, esbuild and so on) or a
   zero-build setup. ES modules and asset loading often fail from
   `file://`, so say exactly how the game runs during development and in
   production.
4. Testing: unit and end-to-end tools.
5. Deployment: static hosting (Netlify, Vercel, GitHub Pages, itch.io),
   plus offline support (PWA).
6. Assets: procedural or a sprite atlas, audio format and generation.

Write `PLAN.md` with: the tech stack decision record (options, choice,
trade-offs, risks); the game design (core loop, enemy types, scoring,
lives, stage progression, power-ups, art and audio direction); the
architecture and folder structure; a risk list; a definition of done per
milestone; and any change to milestones M1 to M9 your stack needs.

Then set up the project: the tooling, the `package.json` scripts above,
one real unit test, and a page that draws a blank canvas that fits the
window, with letterboxing.

```acceptance
[{"kind": "file_contains", "path": "PLAN.md", "contains": "Definition of done"},
 {"kind": "file_exists", "path": "package.json"},
 {"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M0"}]
```

## M1 — Engine core

A fixed-timestep loop (60 Hz update, interpolated rendering), a scene
manager (boot, menu, play, pause, game over), an input layer (keyboard
first), resize handling with letterboxing, an asset loader, and a debug
overlay (FPS, entity count). Unit tests for the loop and the scene
manager.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M1"}]
```

## M2 — Player and shooting

The player's ship moves within the screen, with a shot cooldown and
pooled bullets (no allocation in each frame), over a parallax starfield.
Tune the feel: acceleration, firing rhythm.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M2"}]
```

## M3 — Enemies and formation

An enemy base type and at least three enemy types, a grid formation that
sways while idle, scripted entry paths (Bézier or spline waves),
collision detection (the approach justified in the plan), particle
explosions, scoring and a HUD.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M3"}]
```

## M4 — Attacks and waves

Dive-bomb attack patterns, enemy shots with difficulty scaling, a
data-driven wave and stage manager (JSON or config files), challenge or
bonus stages, player lives, respawn with a short invulnerability, and the
game-over flow.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M4"}]
```

## M5 — Signature mechanics

A twist of your own on the genre (for example capturing a ship and
rescuing it for double fire, or an original mechanic), power-ups, and a
boss every few stages. Document a balance pass.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M5"}]
```

## M6 — Audio and visual polish

Sound effects and a music loop (generated or properly licensed), volume
and mute controls, screen shake, hit flashes, better particles, an
optional CRT or bloom effect that can be turned off, a consistent art
style, and efficient sprite drawing.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M6"}]
```

## M7 — UX, settings and saved scores

A title screen, settings (controls, audio, accessibility: reduced motion,
a colour-blind-safe palette), a pause menu, a tutorial prompt, a
high-score table saved in `localStorage`, touch controls and gamepad
support, layouts that fit any screen, and all text in one place, ready
for translation.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M7"}]
```

## M8 — Quality and performance

Test coverage of the core logic, end-to-end smoke tests (with the tools
chosen in M0), profiling to hold 60 FPS on mid-range phones, a memory and
garbage-collection check, error handling and crash logging, testing in
Chrome, Firefox and Safari (mark a browser you can't run as not checked),
and an accessibility check.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M8"}]
```

## M9 — Production release

A production build with minification and compression, offline support
(PWA), favicon, meta and social tags, an optional opt-in analytics hook
that respects privacy (off by default, sending nothing), the deployment
configuration for the chosen host, a `README.md` with how to run, build
and deploy, a license, and a final QA checklist. Mark the version 1.0.0
in `package.json`; don't deploy or publish anything.

```acceptance
[{"kind": "file_contains", "path": "package.json", "contains": "\"version\": \"1.0.0\""},
 {"kind": "file_contains", "path": "README.md", "contains": "npm run build"},
 {"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## M9"}]
```
