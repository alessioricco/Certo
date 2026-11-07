# Sky Hopper: a side-scrolling platform game in the browser

Needs Node 18 or newer, for the tests. No npm packages: there is nothing
to install. A bigger sample, in milestones: run it with

```bash
certo --milestones tasks/sky-hopper.md --project sky-hopper
```

Build an original side-scrolling platform game in plain JavaScript, HTML
and CSS: a small hero runs and jumps through a level much wider than the
screen, the camera follows, and three background layers scroll at
different speeds (parallax). Original look and level: no characters,
names or art from an existing game.

## Rules for every milestone

- `game.js` holds every rule (tiles, physics, camera, enemies, scoring)
  as plain functions or classes, with no canvas, DOM or keyboard code. It
  must load both as a plain `<script>` in the browser (no
  `import`/`export`) and with `require` in Node, so it ends with
  `if (typeof module !== "undefined") module.exports = { ... };`.
- `main.js`: drawing, keyboard input and the game loop, using `game.js`.
  `index.html` loads `game.js` then `main.js`. Opening `index.html` in a
  browser starts the game, with no server.
- Draw on a canvas that fits the window and follows resizes. Movement uses
  the time between frames, so the speed doesn't depend on the frame rate.
- `game.test.js`: tests with Node's built-in test runner (`node:test` and
  `node:assert`). Every example in a table below goes into it, copied as
  written: they are worked out already, don't change them. Each milestone
  adds its own tests and keeps the earlier ones passing.
- `package.json`: no dependencies, and `"scripts": { "test": "node --test" }`.
- `README.md`: how to open the game, the keys, and how to run the tests.

A level is an array of strings, one per row of 16×16-pixel tiles, and
`level[row][column]` is the tile: `#` ground, `=` brick, `?` bonus block,
`o` a coin, `e` where an enemy starts, `P` where the hero starts, `F` the
flag at the end, a space empty air. `TILE` is 16. In the examples,
`SMALL` is this level:

```js
const SMALL = ["          ", "   ?  o   ", "          ", "##### ####"];
```

## Milestone 1: The level and the camera

Write a first level, at least 200 tiles wide and 15 tall, with gaps,
platforms at several heights, bricks and bonus blocks. Draw the tiles
that are on screen, and a hero as a rectangle that moves left and right
with the arrow keys (or A and D), with no gravity yet. The camera follows
the hero.

| Function | Examples |
| --- | --- |
| `tileAt(level, x, y)`: the tile at pixel `x`, `y`; left or right of the level is ground (`#`), above or below it is air (`" "`) | `tileAt(SMALL, 50, 20)` → `"?"`; `tileAt(SMALL, 100, 20)` → `"o"`; `tileAt(SMALL, 85, 50)` → `" "`; `tileAt(SMALL, -5, 10)` → `"#"`; `tileAt(SMALL, 170, 10)` → `"#"`; `tileAt(SMALL, 20, 70)` → `" "`; `tileAt(SMALL, 20, -10)` → `" "` |
| `isSolid(tile)`: ground, brick and bonus block are solid | `"#"` → `true`; `"="` → `true`; `"?"` → `true`; `"o"` → `false`; `" "` → `false` |
| `cameraX(heroX, viewWidth, levelWidth)`: the camera's left edge, keeping the hero in the middle, but never past the level's edges | `cameraX(100, 320, 2000)` → `0`; `cameraX(1000, 320, 2000)` → `840`; `cameraX(1950, 320, 2000)` → `1680`; `cameraX(50, 320, 200)` → `0` |

```acceptance
[{"kind": "file_contains", "path": "game.js", "contains": "cameraX"},
 {"kind": "file_exists", "path": "index.html"}]
```

## Milestone 2: Running and jumping

The hero now falls, lands on solid tiles, and can't walk through them.
Space (or the up arrow) jumps, only when standing on something; holding
it longer jumps higher, up to a limit. Speed builds up and slows down
instead of starting and stopping at once. Falling into a gap below the
level costs a life and starts the hero again at `P`; the hero has 3 lives.

| Function | Examples |
| --- | --- |
| `applyGravity(vy, dt)`: the vertical speed after `dt` seconds of a 1800 px/s² gravity, never faster than 900 px/s downwards | `applyGravity(0, 0.25)` → `450`; `applyGravity(800, 0.25)` → `900`; `applyGravity(-600, 0.25)` → `-150` |

Add tests of your own for landing: a hero standing on ground stays on it
after a step, and one walking into a wall stops at the wall.

```acceptance
[{"kind": "file_contains", "path": "game.js", "contains": "applyGravity"}]
```

## Milestone 3: Parallax, coins and blocks

Behind the level, draw three background layers: a far sky with clouds, a
middle layer of hills, and a near layer of trees or buildings. Each layer
repeats horizontally and scrolls slower than the level: the far one at a
quarter of the camera's speed, the middle at a half, the near at three
quarters. Coins (`o`) disappear when touched and score 100. Hitting a
bonus block (`?`) from below gives a coin and turns it into a used block;
bricks (`=`) stop the hero but don't break. Score, coins and lives are
always on screen.

| Function | Examples |
| --- | --- |
| `layerShift(cameraX, factor)`: how far a background layer has scrolled left | `layerShift(200, 0.5)` → `100`; `layerShift(200, 0.25)` → `50`; `layerShift(1000, 0.25)` → `250`; `layerShift(999, 0.5)` → `499.5`; `layerShift(200, 0)` → `0` |

```acceptance
[{"kind": "file_contains", "path": "game.js", "contains": "layerShift"}]
```

## Milestone 4: Enemies, the flag and the next level

Enemies (`e`) walk left and right, turn round at walls and at the edge of
a gap, and fall under gravity like the hero. Landing on an enemy from
above (a stomp) removes it, scores 200 and bounces the hero up; touching
it any other way costs a life. Reaching the flag (`F`) ends the level with
a bonus for the time left (a 300-second timer is on screen) and starts a
second level of your own, harder than the first. Losing the last life
shows "Game over"; Enter starts a new game. P pauses and resumes.

`stomps(hero, enemy)` takes two boxes, `{ x, y, w, h }` in pixels with
`y` growing downwards, the hero's also with its vertical speed `vy`. It is
true when the boxes overlap, the hero is falling (`vy > 0`), and the
hero's bottom edge is no lower than the middle of the enemy.

| Function | Examples |
| --- | --- |
| `stomps(hero, enemy)` | `stomps({ x: 10, y: 0, w: 12, h: 16, vy: 200 }, { x: 12, y: 12, w: 16, h: 16 })` → `true`; `stomps({ x: 10, y: 0, w: 12, h: 16, vy: -50 }, { x: 12, y: 12, w: 16, h: 16 })` → `false`; `stomps({ x: 10, y: 10, w: 12, h: 16, vy: 200 }, { x: 12, y: 12, w: 16, h: 16 })` → `false`; `stomps({ x: 10, y: 0, w: 12, h: 16, vy: 200 }, { x: 40, y: 12, w: 16, h: 16 })` → `false` |

Add a test that the game is over when the last life is lost.

```acceptance
[{"kind": "file_contains", "path": "game.js", "contains": "stomps"},
 {"kind": "file_contains", "path": "README.md", "contains": "npm test"}]
```
