const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { parseHours, isOpen } = require(path.join(process.cwd(), "openingHours.js"));

const r = (day, from, to) => ({ day, from, to });

test("one day, one range", () => {
  assert.deepStrictEqual(parseHours("Sat 10:00-16:00"), [r(5, 600, 960)]);
});

test("a day range and two time ranges", () => {
  const got = parseHours("Mon-Fri 09:00-12:30,14:00-18:00");
  assert.strictEqual(got.length, 10);
  assert.deepStrictEqual(got.slice(0, 2), [r(0, 540, 750), r(0, 840, 1080)]);
  assert.deepStrictEqual(got[9], r(4, 840, 1080));
});

test("several rules, sorted by day then from", () => {
  assert.deepStrictEqual(parseHours("Sun 12:00-13:00; Mon 08:00-09:00; Sun 09:00-10:00"), [
    r(0, 480, 540),
    r(6, 540, 600),
    r(6, 720, 780),
  ]);
});

test("a day list with a range in it", () => {
  const days = parseHours("Mon,Wed,Fri-Sun 10:00-11:00").map((x) => x.day);
  assert.deepStrictEqual(days, [0, 2, 4, 5, 6]);
});

test("a range that wraps past Sunday", () => {
  const days = parseHours("Fri-Mon 10:00-11:00").map((x) => x.day);
  assert.deepStrictEqual(days, [0, 4, 5, 6]);
});

test("spaces around separators", () => {
  assert.deepStrictEqual(
    parseHours("  Mon - Tue  09:00 - 10:00 , 11:00-12:00 ;Sat 10:00-11:00 "),
    parseHours("Mon-Tue 09:00-10:00,11:00-12:00;Sat 10:00-11:00"),
  );
});

test("empty text means always closed", () => {
  assert.deepStrictEqual(parseHours(""), []);
  assert.deepStrictEqual(parseHours("   "), []);
});

test("overlapping and touching ranges are merged", () => {
  assert.deepStrictEqual(parseHours("Mon 09:00-12:00,11:00-13:00"), [r(0, 540, 780)]);
  assert.deepStrictEqual(parseHours("Mon 09:00-10:00; Mon 10:00-11:00"), [r(0, 540, 660)]);
  assert.deepStrictEqual(parseHours("Tue 08:00-18:00,09:00-10:00"), [r(1, 480, 1080)]);
});

test("midnight bounds", () => {
  assert.deepStrictEqual(parseHours("Sun 00:00-24:00"), [r(6, 0, 1440)]);
});

for (const text of [
  "Mon",
  "Mon 9:00-10:00",
  "Mon 09:60-10:00",
  "Mon 24:30-24:45",
  "Mon 10:00-09:00",
  "Mon 10:00-10:00",
  "Mon 22:00-02:00",
  "Mo 09:00-10:00",
  "Mon-Fri-Sat 09:00-10:00",
  "Mon 09:00",
  "09:00-10:00",
  "Mon 09:00-10:00;",
]) {
  test(`throws SyntaxError for ${JSON.stringify(text)}`, () => {
    assert.throws(() => parseHours(text), SyntaxError);
  });
}

test("isOpen uses Monday as day 0", () => {
  const hours = "Mon 09:00-17:00";
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 16, 10, 0)), true); // a Monday
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 15, 10, 0)), false); // a Sunday
  assert.strictEqual(isOpen("Sun 09:00-17:00", new Date(2026, 10, 15, 10, 0)), true);
});

test("isOpen: from included, to excluded", () => {
  const hours = "Tue 09:00-17:00";
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 17, 9, 0)), true);
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 17, 16, 59)), true);
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 17, 17, 0)), false);
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 17, 8, 59)), false);
});

test("isOpen between two ranges, and when always closed", () => {
  const hours = "Wed 09:00-12:30,14:00-18:00";
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 18, 13, 0)), false);
  assert.strictEqual(isOpen(hours, new Date(2026, 10, 18, 14, 0)), true);
  assert.strictEqual(isOpen("", new Date(2026, 10, 18, 14, 0)), false);
});
