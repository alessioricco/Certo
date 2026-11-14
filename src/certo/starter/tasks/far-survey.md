# Far Survey: an exploration game on an alien world, in the browser

Needs Node 18 or newer. A big sample, in milestones: run it with

```bash
certo --milestones tasks/far-survey.md --project far-survey
```

Build an original first-person exploration game for the browser, in
TypeScript with Three.js: the player lands on an alien planet and
surveys it on foot, under an alien sun. The sky, the terrain, the plants
and the animals are generated from the planet's physical description, so
every world looks different but stays credible: a red dwarf gives a
reddish light and dark plants, strong gravity gives low jumps and squat
animals, a thick atmosphere hides the stars. Most life is harmless; some
predators defend their territory. Original look and names: nothing taken
from an existing game.

The game engine and the worlds are separate. A world (a "level") is a
small JSON file in the `levels/` folder, or at any URL: adding a world
means adding a file, never changing the engine.

## Rules for every milestone

- **Stack:** TypeScript, Vite for the dev server and the build, Three.js
  for 3D, Vitest for tests, `simplex-noise` for terrain noise. Open-source
  packages only, listed in `THIRD_PARTY_NOTICES.md` with their licenses.
  No other runtime dependency without a reason written in `DECISIONS.md`.
- **Layout:**
  - `src/engine/`: the physics, the world generation and every game rule,
    as plain TypeScript functions and classes. Nothing in it imports
    Three.js or touches the DOM, so all of it runs in Node and in tests.
  - `src/render/`: everything Three.js (meshes, materials, the camera,
    the sky), built from what `src/engine/` computes.
  - `src/main.ts`: input, the game loop and the page. `index.html` loads it.
  - `levels/`: the worlds, one JSON file each, plus `levels/index.json`
    listing them.
- **Same seed, same world:** all randomness comes from the level's `seed`
  through `mulberry32` (below), never `Math.random`, so a world is the same
  every time it loads.
- **Scripts in `package.json`:** `dev`, `build` (type check, then Vite
  build), `test` (`vitest run`), `typecheck` and `lint` (ESLint, no
  warnings). Each milestone keeps all of them passing.
- **Tests:** every example in a table below goes into a test, copied as
  written: they are worked out already, don't change them. Compare real
  numbers within 0.01. Each milestone adds its own tests and keeps the
  earlier ones passing.
- **Units:** SI inside the engine (metres, seconds, kelvin, m/s²). Planet
  mass and radius in level files are in Earth units, star luminosity in
  solar units, orbit distance in astronomical units (AU).
- **Look:** stylized low-poly: flat-shaded geometry, a limited palette per
  world, atmospheric fog. Movement uses the time between frames, so speed
  doesn't depend on the frame rate.
- `README.md`: how to run it, the controls, how to run the tests.
  `CHANGELOG.md`: one section per milestone, `## Milestone N: title`, with
  what changed and how to check it by hand.

## A level file

```json
{
  "id": "verdant-g",
  "name": "Verdant",
  "seed": 42,
  "star": { "class": "G" },
  "planet": {
    "massEarths": 1.0,
    "radiusEarths": 1.0,
    "orbitAU": 1.0,
    "albedo": 0.3,
    "dayLengthHours": 24,
    "atmosphere": { "pressureAtm": 1.0, "oxygenFraction": 0.21 }
  },
  "objectives": [
    { "kind": "scan-species", "count": 5 },
    { "kind": "reach-landmark", "name": "the tall spire" }
  ],
  "assets": {}
}
```

Star classes, for the engine (main-sequence values, approximate):

| Class | Temperature (K) | Luminosity (Sun = 1) |
| --- | --- | --- |
| M | 3200 | 0.04 |
| K | 4500 | 0.35 |
| G | 5778 | 1.0 |
| F | 6500 | 2.5 |
| A | 9000 | 20 |

## Milestone 1: Worlds as data, and their physics

The project, the level format and the physics that everything later is
built on. `levels/index.json` lists the worlds (`[{ "id", "file" }]`).
`loadLevel(source)` reads a level from a file in `levels/` or from a URL
(`?level=<id or URL>` on the page), and `validateLevel(json)` returns a
list of plain-language errors (an empty list when the level is valid):
a missing field, a number out of range (mass 0.1 to 10, radius 0.3 to 3,
pressure 0 to 10, oxygen 0 to 1, a known star class). An invalid level
shows its errors on the page instead of a broken world. For now the page
shows the world's computed facts: gravity, escape velocity, temperature,
whether it is in the habitable zone, whether the air is breathable.

Three levels in `levels/`: `verdant-g` (above), `ember-m` (class M,
mass 0.8, radius 0.95, orbit 0.15 AU, albedo 0.3, pressure 0.5, oxygen
0.25, day 60 hours, seed 7) and `boulder-k` (class K, mass 5, radius 1.5,
orbit 0.6 AU, albedo 0.3, pressure 2, oxygen 0.15, day 18 hours, seed
1234).

| Function | Examples |
| --- | --- |
| `mulberry32(seed)`: a function returning the next random number in [0, 1), the standard Mulberry32 (32-bit integer operations) | three calls of `mulberry32(1)` → `0.6270739406`, `0.0027357212`, `0.52744704`; three calls of `mulberry32(42)` → `0.6011037519`, `0.448290559`, `0.8524657935` |
| `surfaceGravity(massEarths, radiusEarths)`: `9.81 · M / R²` in m/s² | `(1, 1)` → `9.81`; `(2, 1)` → `19.62`; `(1, 2)` → `2.4525`; `(5, 1.5)` → `21.8` |
| `escapeVelocity(massEarths, radiusEarths)`: `11.186 · √(M / R)` in km/s | `(1, 1)` → `11.186`; `(4, 1)` → `22.372`; `(5, 1.5)` → `20.4227` |
| `equilibriumTemperature(luminosity, orbitAU, albedo)`: `278.6 · (1 − A)^¼ · L^¼ / √d` in kelvin | `(1, 1, 0.3)` → `254.83`; `(0.04, 0.15, 0.3)` → `294.26`; `(2.5, 2, 0.2)` → `234.27`; `(0.35, 0.6, 0.3)` → `253.04` |
| `surfaceTemperature(luminosity, orbitAU, albedo, pressureAtm)`: the equilibrium temperature plus a simple greenhouse effect, `+ 33 · pressureAtm` | `(1, 1, 0.3, 1)` → `287.83`; `(0.35, 0.6, 0.3, 2)` → `319.04`; `(2.5, 2, 0.2, 0.1)` → `237.57` |
| `habitableZone(luminosity)`: `{ inner: √(L / 1.1), outer: √(L / 0.53) }` in AU | `(1)` → `{ inner: 0.9535, outer: 1.3736 }`; `(0.04)` → `{ inner: 0.1907, outer: 0.2747 }` |
| `oxygenPartialPressure(pressureAtm, oxygenFraction)`: their product; the air is breathable from 0.16 to 0.5 atm | `(1, 0.21)` → `0.21` (breathable); `(0.5, 0.21)` → `0.105` (too thin); `(3, 0.21)` → `0.63` (toxic) |

```acceptance
[{"kind": "file_exists", "path": "levels/index.json"},
 {"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 1"}]
```

## Milestone 2: Terrain and walking

The player stands on the planet and walks in first person: mouse look
(pointer lock), WASD to move, Space to jump, Shift to run. The terrain is
generated from the seed with layered `simplex-noise` (a few octaves:
broad hills, then detail), built in square chunks around the player that
appear ahead and are dropped behind, so the world feels endless. The
player follows the ground, can't walk up slopes steeper than 45°, and
falls with the planet's gravity: on `boulder-k` jumps are low and heavy,
on a light world high and floaty. Low-poly, flat-shaded ground, coloured
by height and slope (rock on steep slopes).

| Function | Examples |
| --- | --- |
| `jumpHeight(gravity)`: the height of a jump at 3.13 m/s take-off speed, `3.13² / (2 · g)` in metres | `(9.81)` → `0.4993`; `(19.62)` → `0.2497`; `(2.4525)` → `1.9973` |
| `terrainHeight(x, z, seed)`: the ground height at a point | the same `(x, z, seed)` always gives the same height; a different seed gives a different landscape (test both) |

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 2"}]
```

## Milestone 3: An alien sky

The star is a glowing disc whose colour comes from its temperature; the
sky's colour comes from that light scattered by the atmosphere (Rayleigh
scattering, strongest for blue). The star crosses the sky once per day
length: dawn, day, dusk and night, with the light and fog colour following
it. At night stars appear, fewer through a thick atmosphere. Fog density
grows with the atmosphere's pressure. A small moon or two (from the seed)
may cross the sky.

| Function | Examples |
| --- | --- |
| `blackbodyColor(kelvin)`: an `[r, g, b]` (0–255, whole numbers) for a star's temperature, with the widely used Tanner Helland approximation: with `t = kelvin / 100`, red is 255 for `t ≤ 66`, else `329.698727446 · (t − 60)^−0.1332047592`; green is `99.4708025861 · ln(t) − 161.1195681661` for `t ≤ 66`, else `288.1221695283 · (t − 60)^−0.0755148492`; blue is 255 for `t ≥ 66`, 0 for `t ≤ 19`, else `138.5177312231 · ln(t − 10) − 305.0447927307`; each clamped to 0–255 and rounded | `(3200)` → `[255, 184, 123]`; `(5778)` → `[255, 242, 231]`; `(6500)` → `[255, 254, 250]`; `(10000)` → `[202, 218, 255]` |
| `skyColor(kelvin)`: the star's colour with each channel weighted by Rayleigh scattering, `(550 / λ)⁴` for λ = 700, 550 and 450 nm (red, green, blue), scaled so the largest channel is 255, rounded | `(3200)` → `[90, 171, 255]`; `(5778)` → `[48, 120, 255]`; `(10000)` → `[34, 98, 255]` |
| `starElevation(timeHours, dayLengthHours)`: the star's height above the horizon in degrees, `asin(sin(2π · t / day))` | `(0, 24)` → `0`; `(6, 24)` → `90`; `(9, 24)` → `45`; `(18, 24)` → `-90` |
| `visibleStarFraction(pressureAtm)`: how many of the night's stars show, `clamp(1 − p / 3, 0, 1)` | `(0)` → `1`; `(1.5)` → `0.5`; `(3)` → `0`; `(4)` → `0` |

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 3"}]
```

## Milestone 4: Plants and animals

Life follows the world. Plants grow where it is neither too steep nor too
high nor too cold or hot, denser near water-filled lowlands, in a few
species per world, each a low-poly shape from a few generated parts
(stalks, fronds, caps). Their colour follows the star: on a red dwarf
nearly black or deep purple (they absorb all the dim light), under a
K star red to orange, under a G star green, under hotter stars bluish.
Animals are built the same way (body, legs, head), in herds that graze
and wander and flee when the player runs at them; their size follows
gravity (squat on heavy worlds, tall and slender on light ones). Every
species gets a generated name and a short description. The scanner
(right mouse button, aimed) identifies a plant or animal and adds it to
the survey log (Tab), once per species.

| Function | Examples |
| --- | --- |
| `bodyScale(gravity)`: how big animals grow compared with Earth, `(9.81 / g)^½`, kept between 0.3 and 3 | `(9.81)` → `1`; `(39.24)` → `0.5`; `(2.4525)` → `2`; `(100)` → `0.3132`; `(0.5)` → `3` |
| `plantHue(kelvin)`: one of `"black"` (below 3500 K), `"red"` (3500 to 4999), `"green"` (5000 to 6499), `"blue"` (6500 and above) | `(3200)` → `"black"`; `(4500)` → `"red"`; `(5778)` → `"green"`; `(9000)` → `"blue"` |

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 4"}]
```

## Milestone 5: Survival and danger

The planet is dangerous without care. The suit has oxygen (drained faster
when running; refilled at the lander, or not needed where the air is
breathable), and a temperature limit: too hot or too cold outside slowly
costs health. Some animal species are predators: each defends a territory
(shown subtly, by bones and marks on the ground), warns with a sound and
a posture when the player enters it, and attacks if the player stays.
The sampling tool (left mouse button) stuns a creature for a few seconds,
with a cooldown; it never kills. Health, oxygen and temperature are on
screen. At zero health the player wakes at the lander, keeping the survey
log. Add tests of your own for the oxygen drain, the territory check and
the stun cooldown, as engine functions.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 5"}]
```

## Milestone 6: Objectives, worlds from anywhere, assets

A world's `objectives` drive the game: scan a number of species, reach a
named landmark (a striking generated feature such as a spire or an arch,
placed from the seed), return to the lander. Completing them all shows a
survey report: the planet's facts and the species found. Progress is
kept per world in the browser's `localStorage`. A title screen lists the
worlds from `levels/index.json` and has a field for a level URL. A
level's optional `assets` can point to glTF models or textures by path or
URL for named species or the lander; when one can't be loaded, the
generated version is used and a note says so. Write `LEVELS.md`: the
level format, every field and its range, the star classes, and how to
publish a world at a URL.

```acceptance
[{"kind": "file_exists", "path": "LEVELS.md"},
 {"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 6"}]
```

## Milestone 7: Feel and speed

Make it smooth and alive. A steady 60 frames per second on a mid-range
laptop: fewer, simpler chunks and plants far away, objects outside the
view not drawn, generation spread over frames so walking never stutters.
Sound made in the browser with Web Audio, from the world (wind stronger
in a thick atmosphere, animal calls, the scanner), with a mute key (M).
Footsteps and head bob that follow gravity. A settings panel (draw
distance, mouse sensitivity, volume) kept in `localStorage`. P pauses.
A frame-time check in the tests: generating one chunk with its plants
stays under a time limit you choose and write down in `DECISIONS.md`.

```acceptance
[{"kind": "file_contains", "path": "CHANGELOG.md", "contains": "## Milestone 7"}]
```
