---
name: node-project-setup
triggers:
  - node
  - node.js
  - nodejs
  - npm
  - javascript
  - typescript
description: Keep a Node project's package.json checkable, with a real test script, the lockfile and no prompts. Triggered when a task mentions Node, npm, JavaScript or TypeScript.
---

When the project is a Node project (it has, or will have, a
`package.json`), keep it checkable:

- A real `test` script that runs at least one test and exits with an
  error when a test fails (`node --test`, or the project's test
  framework). `npm init`'s placeholder (`echo "Error: no test
  specified" && exit 1`) is not a test.
- A `build` script when the project has a build step, and nothing that
  waits for input or keeps running (no watch mode, no dev server) in
  `test` or `build`.
- Install with `npm install <package>` (or `--save-dev` for tools only
  the tests and build use) so `package.json` and `package-lock.json`
  both record it; keep the lockfile. When a lockfile exists, `npm ci`
  installs exactly what it lists.
- Create projects with the non-interactive form of a scaffolder
  (`npm init -y`, `--yes`, `--no-interactive`, a `--template`); a prompt
  with no one to answer it creates nothing.
- Run `npm test` (and `npm run build` if there is one) before finishing.
