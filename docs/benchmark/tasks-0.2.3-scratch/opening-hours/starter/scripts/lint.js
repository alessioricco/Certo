// The project's style check: shipped code logs nothing.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const skip = new Set(["node_modules", ".git", "scripts", ".certo", ".venv"]);
const problems = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(c|m)?js$/.test(entry.name)) check(full);
  }
}

function check(file) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    if (/\bconsole\.log\s*\(/.test(line)) {
      problems.push(`${path.relative(root, file)}:${i + 1}: console.log is not allowed`);
    }
  });
}

walk(root);
for (const p of problems) console.error(p);
if (problems.length) {
  console.error(`${problems.length} problem(s)`);
  process.exit(1);
}
