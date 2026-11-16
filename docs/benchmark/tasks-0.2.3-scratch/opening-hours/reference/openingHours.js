const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function bad(why) {
  return new SyntaxError(`invalid opening hours: ${why}`);
}

function dayIndex(name) {
  const i = DAYS.indexOf(name.trim());
  if (i < 0) throw bad(`unknown day "${name.trim()}"`);
  return i;
}

function parseDays(text) {
  const days = new Set();
  for (const part of text.split(",")) {
    const ends = part.split("-");
    if (ends.length === 1) days.add(dayIndex(ends[0]));
    else if (ends.length === 2) {
      const a = dayIndex(ends[0]);
      const b = dayIndex(ends[1]);
      for (let d = a; ; d = (d + 1) % 7) {
        days.add(d);
        if (d === b) break;
      }
    } else throw bad(`bad days "${part}"`);
  }
  return days;
}

function parseTime(text) {
  const m = /^(\d\d):(\d\d)$/.exec(text.trim());
  if (!m) throw bad(`bad time "${text.trim()}"`);
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (min > 59 || h > 24 || (h === 24 && min !== 0)) throw bad(`bad time "${text.trim()}"`);
  return h * 60 + min;
}

function parseRange(text) {
  const ends = text.split("-");
  if (ends.length !== 2) throw bad(`bad range "${text.trim()}"`);
  const from = parseTime(ends[0]);
  const to = parseTime(ends[1]);
  if (to <= from) throw bad(`range "${text.trim()}" ends before it starts`);
  return [from, to];
}

function parseHours(text) {
  if (typeof text !== "string") throw bad("not a string");
  if (text.trim() === "") return [];
  const perDay = new Map();
  for (const rule of text.split(";")) {
    const m = /^\s*(\S+(?:\s*[-,]\s*\S+)*?)\s+(\d.*)$/.exec(rule);
    if (!m) throw bad(`bad rule "${rule.trim()}"`);
    const days = parseDays(m[1].replace(/\s+/g, ""));
    const ranges = m[2].split(",").map(parseRange);
    for (const d of days) {
      if (!perDay.has(d)) perDay.set(d, []);
      perDay.get(d).push(...ranges);
    }
  }
  const out = [];
  for (const d of [...perDay.keys()].sort((a, b) => a - b)) {
    const ranges = perDay.get(d).sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [from, to] of ranges) {
      const last = merged[merged.length - 1];
      if (last && from <= last[1]) last[1] = Math.max(last[1], to);
      else merged.push([from, to]);
    }
    for (const [from, to] of merged) out.push({ day: d, from, to });
  }
  return out;
}

function isOpen(text, date) {
  const day = (date.getDay() + 6) % 7;
  const minutes = date.getHours() * 60 + date.getMinutes();
  return parseHours(text).some((r) => r.day === day && r.from <= minutes && minutes < r.to);
}

module.exports = { parseHours, isOpen };
