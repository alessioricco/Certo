# Opening hours

Write a Node.js module with no dependencies. `package.json` is already
here; keep it CommonJS and keep `npm test` running `node --test`.

## `openingHours.js`

Export two functions with `module.exports = { parseHours, isOpen }`.

`parseHours(text)` reads a shop's opening hours and returns a list of
`{ day, from, to }` objects, one per day and time range, sorted by day,
then by `from`:

- `day`: `0` for Monday up to `6` for Sunday.
- `from`, `to`: minutes since midnight, `from` included, `to` excluded.

The text is one or more rules separated by `;`. A rule is a set of days,
a space, and one or more time ranges separated by `,`:

```text
Mon-Fri 09:00-12:30,14:00-18:00; Sat 10:00-16:00
```

- Days are written `Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, `Sun`. A
  set of days is one day, a range (`Mon-Fri`), or several of these
  separated by `,` (`Mon,Wed,Fri-Sun`). A range may wrap past Sunday:
  `Fri-Mon` is Friday, Saturday, Sunday and Monday.
- A time is `HH:MM`, from `00:00` to `24:00`. In a range, the end must
  be after the start (no range goes past midnight).
- Spaces around `;`, `,` and `-` are allowed, and an empty text, or one
  with only spaces, means always closed (an empty list).
- When two ranges on the same day overlap or touch, they become one
  (`09:00-12:00,11:00-13:00` is `09:00-13:00`).
- Anything else (an unknown day, a bad time, a missing part, an end not
  after its start) throws a `SyntaxError`.

`isOpen(text, date)` returns `true` when the shop is open at the local
time of the JavaScript `Date` `date`, otherwise `false`.

JavaScript's `Date` numbers the days differently from this format: try a
few dates in a quick script first, to be sure of how they map.

Also write tests in `openingHours.test.js`, using `node:test` and
`node:assert`.
