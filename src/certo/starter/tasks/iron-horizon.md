# Iron Horizon: a 3D tank game in the browser

Needs Node 18 or newer, for the tests. No npm packages and no 3D library:
the 3D drawing is your own code on a plain canvas. A bigger sample, in
milestones: run it with

```bash
certo --milestones tasks/iron-horizon.md --project iron-horizon
```

Build an original first-person tank game in plain JavaScript, HTML and
CSS, drawn in glowing wireframe lines on black: the player drives a tank
across a flat plain with obstacles and mountains on the horizon, and
fights enemy tanks. Original look and names: nothing taken from an
existing game.

## Rules for every milestone

- `engine.js` holds the 3D maths and every game rule (movement,
  collisions, shells, enemies, scoring) as plain functions or classes,
  with no canvas, DOM or keyboard code. It must load both as a plain
  `<script>` in the browser (no `import`/`export`) and with `require` in
  Node, so it ends with
  `if (typeof module !== "undefined") module.exports = { ... };`.
- `main.js`: drawing, keyboard input and the game loop, using
  `engine.js`. `index.html` loads `engine.js` then `main.js`. Opening
  `index.html` in a browser starts the game, with no server.
- Draw on a canvas that fits the window and follows resizes. Movement uses
  the time between frames, so the speed doesn't depend on the frame rate.
- `engine.test.js`: tests with Node's built-in test runner (`node:test`
  and `node:assert`). Every example in a table below goes into it, copied
  as written: they are worked out already, don't change them. Where an
  example says "within 1e-9", compare each number with that tolerance:
  turning by a right angle gives values such as `3.06e-16` instead of `0`.
  Each milestone adds its own tests and keeps the earlier ones passing.
- `package.json`: no dependencies, and `"scripts": { "test": "node --test" }`.
- `README.md`: how to open the game, the keys, and how to run the tests.

The world: `x` to the right, `y` up, `z` forwards, in metres. The ground
is `y = 0`. A camera (the player's tank) is `{ x, z, heading }`, where
`heading` is in radians: `0` looks along `+z`, and a growing heading turns
right, towards `+x`. A point `{ x, y, z }` is turned into the camera's
view with `toCamera`, then onto the screen with `project`.

## Milestone 1: The 3D view and driving

Draw the plain as a grid of ground lines, and at least ten obstacles
(cubes and pyramids as wireframe models) placed around the player. The
up and down arrows (or W and S) drive forwards and backwards, left and
right (or A and D) turn the tank. Lines that go behind the camera are cut
at the near plane (`z = 0.1`) instead of being dropped or drawn wrongly.

| Function | Examples |
| --- | --- |
| `toCamera(point, camera)`: the point as seen from the camera: move it by the camera's position, then turn it by the camera's heading. With `dx = point.x - camera.x` and `dz = point.z - camera.z`: `x = dx·cos(h) - dz·sin(h)`, `y = point.y`, `z = dx·sin(h) + dz·cos(h)` | `toCamera({ x: 5, y: 0, z: 10 }, { x: 1, z: 2, heading: 0 })` → `{ x: 4, y: 0, z: 8 }`; within 1e-9: `toCamera({ x: 5, y: 1, z: 0 }, { x: 0, z: 0, heading: Math.PI / 2 })` → `{ x: 0, y: 1, z: 5 }`; within 1e-9: `toCamera({ x: 0, y: 0, z: 5 }, { x: 0, z: 0, heading: Math.PI / 2 })` → `{ x: -5, y: 0, z: 0 }` |
| `project(point, focal, width, height)`: a camera-space point onto the screen, or `null` when `point.z` is 0.1 or less: `x = width/2 + point.x·focal/point.z`, `y = height/2 - point.y·focal/point.z` | `project({ x: 2, y: 1, z: 4 }, 200, 640, 480)` → `{ x: 420, y: 190 }`; `project({ x: -3, y: -2, z: 10 }, 300, 800, 600)` → `{ x: 310, y: 360 }`; `project({ x: 0, y: 0, z: 0 }, 200, 640, 480)` → `null` |
| `clipToNear(a, b, near)`: the part of the camera-space segment `a`–`b` with `z` at least `near`, as `[a, b]` with the end behind replaced by the point where the segment crosses `z = near`; `null` when both ends are behind | `clipToNear({ x: 0, y: 0, z: -1 }, { x: 0, y: 0, z: 3 }, 1)` → `[{ x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: 3 }]`; `clipToNear({ x: 4, y: 2, z: 5 }, { x: 0, y: 0, z: -3 }, 1)` → `[{ x: 4, y: 2, z: 5 }, { x: 2, y: 1, z: 1 }]`; `clipToNear({ x: 0, y: 0, z: -1 }, { x: 0, y: 0, z: 0.5 }, 1)` → `null` |
| `wrapAngle(a)`: the same angle between -π (excluded) and π (included) | `wrapAngle(3 * Math.PI / 2)` → `-Math.PI / 2`; `wrapAngle(-3 * Math.PI / 2)` → `Math.PI / 2`; `wrapAngle(Math.PI)` → `Math.PI`; `wrapAngle(-Math.PI)` → `Math.PI`; `wrapAngle(0.5)` → `0.5`; `wrapAngle(5 * Math.PI)` → `Math.PI` |

```acceptance
[{"kind": "file_contains", "path": "engine.js", "contains": "clipToNear"},
 {"kind": "file_exists", "path": "index.html"}]
```

## Milestone 2: The horizon and collisions

A ring of mountains (a jagged wireframe line) sits on the horizon. It
moves sideways as the tank turns and never gets closer as it drives, so
it always looks far away. A crescent moon hangs above it. The tank can't
drive through obstacles: it stops against them.

| Function | Examples |
| --- | --- |
| `circlesHit(a, b)`: whether two circles on the ground, `{ x, z, r }`, touch or overlap | `circlesHit({ x: 0, z: 0, r: 1 }, { x: 3, z: 4, r: 4 })` → `true`; `circlesHit({ x: 0, z: 0, r: 1 }, { x: 3, z: 4, r: 3.9 })` → `false` |

```acceptance
[{"kind": "file_contains", "path": "engine.js", "contains": "circlesHit"}]
```

## Milestone 3: Shells and enemy tanks

Space fires a shell straight ahead; only one of the player's shells can
fly at a time, and a shell stops at an obstacle or after 200 metres. Enemy
tanks (wireframe models of their own) appear one at a time, at a distance:
each turns towards the player, drives closer, and fires when the player is
almost straight ahead. A hit on an enemy scores 1000 and the next enemy
appears; a hit on the player costs one of 3 lives, with a cracked-glass
effect on the screen. Write `turnTowards(heading, from, to, maxTurn)`: the
new heading of a tank at `from` turning towards `to` by at most `maxTurn`
radians, using `wrapAngle`, with tests of your own.

```acceptance
[{"kind": "file_contains", "path": "engine.js", "contains": "turnTowards"}]
```

## Milestone 4: Radar, waves and game over

A round radar at the top of the screen shows the enemies around the
player as dots, turned with the player's heading, with a sweeping line. A
message says when an enemy is behind or to the side. Every 5 enemies
destroyed, the next ones are faster and fire sooner. Score, high score
(kept in the browser's `localStorage`), and lives are always on screen.
Losing the last life shows "Game over"; Enter starts a new game. P pauses
and resumes. Add a test that the game is over when the last life is lost.

```acceptance
[{"kind": "file_contains", "path": "README.md", "contains": "npm test"}]
```
