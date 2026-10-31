// The tally program, run as people run it: `node tally.js FILE...`.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const TALLY = path.join(__dirname, '..', 'tally.js');

function file(text) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tally-'));
  const name = path.join(dir, 'in.txt');
  fs.writeFileSync(name, text);
  return name;
}

function run(...args) {
  const result = spawnSync(process.execPath, [TALLY, ...args], { encoding: 'utf8', timeout: 20000 });
  return { code: result.status, out: result.stdout, err: result.stderr };
}

test('counts words, most frequent first', () => {
  const r = run(file('the cat and the hat and the bat'));
  assert.equal(r.code, 0);
  assert.equal(r.out, '3 the\n2 and\n1 bat\n1 cat\n1 hat\n');
});

test('lower case, and every other character separates words', () => {
  const r = run(file("Hello, HELLO! hello-world it's 42 x42"));
  assert.equal(r.out, '3 hello\n1 42\n1 it\n1 s\n1 world\n1 x42\n');
});

test('accented letters separate words', () => {
  assert.equal(run(file('café cafe café')).out, '2 caf\n1 cafe\n');
});

test('several files are one text, in order', () => {
  const r = run(file('a b\n'), file('b c\n'));
  assert.equal(r.code, 0);
  assert.equal(r.out, '2 b\n1 a\n1 c\n');
});

test('--top keeps the first lines', () => {
  assert.equal(run('--top', '2', file('x y y z z z')).out, '3 z\n2 y\n');
  assert.equal(run(file('x y y z z z'), '--top', '1').out, '3 z\n');
  assert.equal(run('--top', '10', file('a')).out, '1 a\n');
});

test('--min-length leaves out short words', () => {
  assert.equal(run('--min-length', '3', file('a an and ant')).out, '1 and\n1 ant\n');
});

test('both options together', () => {
  const r = run('--min-length', '2', '--top', '1', file('a a a bb bb cc'));
  assert.equal(r.out, '2 bb\n');
});

test('a file with no words prints nothing', () => {
  const r = run(file('  ,,, !! \n'));
  assert.equal(r.code, 0);
  assert.equal(r.out, '');
});

test('no file named is a usage error', () => {
  const r = run();
  assert.equal(r.code, 2);
  assert.equal(r.out, '');
  assert.match(r.err, /^tally: /);
});

test('bad options are usage errors', () => {
  const name = file('a');
  for (const args of [['--top', '0', name], ['--top', 'x', name], ['--top', '1.5', name],
    ['--min-length', '-1', name], [name, '--top'], ['--bogus', name]]) {
    const r = run(...args);
    assert.equal(r.code, 2, args.join(' '));
    assert.equal(r.out, '', args.join(' '));
    assert.match(r.err, /^tally: /, args.join(' '));
  }
});

test('a file that cannot be read exits 1', () => {
  const r = run(path.join(os.tmpdir(), 'no-such-tally-file.txt'));
  assert.equal(r.code, 1);
  assert.equal(r.out, '');
  assert.match(r.err, /^tally: /);
});
