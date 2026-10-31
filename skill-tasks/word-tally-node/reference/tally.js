'use strict';

const fs = require('node:fs');

function usageError(message) {
  process.stderr.write(`tally: ${message}\n`);
  process.exit(2);
}

function wholeNumber(name, value) {
  if (value === undefined) usageError(`${name} needs a value`);
  if (!/^[0-9]+$/.test(value) || Number(value) < 1) {
    usageError(`${name} must be a whole number of at least 1`);
  }
  return Number(value);
}

function parseArgs(argv) {
  const files = [];
  let top = Infinity;
  let minLength = 1;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--top') {
      top = wholeNumber('--top', argv[i + 1]);
      i += 1;
    } else if (arg === '--min-length') {
      minLength = wholeNumber('--min-length', argv[i + 1]);
      i += 1;
    } else if (arg.startsWith('--')) {
      usageError(`unknown option ${arg}`);
    } else {
      files.push(arg);
    }
  }
  if (files.length === 0) usageError('no file named');
  return { files, top, minLength };
}

function tally(text, minLength = 1) {
  const counts = new Map();
  for (const word of text.toLowerCase().match(/[a-z0-9]+/g) || []) {
    if (word.length >= minLength) counts.set(word, (counts.get(word) || 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

function main(argv) {
  const { files, top, minLength } = parseArgs(argv);
  const texts = [];
  for (const file of files) {
    try {
      texts.push(fs.readFileSync(file, 'utf8'));
    } catch {
      process.stderr.write(`tally: cannot read ${file}\n`);
      process.exit(1);
    }
  }
  const lines = tally(texts.join('\n'), minLength)
    .slice(0, top)
    .map(([word, count]) => `${count} ${word}\n`);
  process.stdout.write(lines.join(''));
}

module.exports = { tally };

if (require.main === module) main(process.argv.slice(2));
