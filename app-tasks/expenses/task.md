# Expense ledger

Build a small expense ledger in Python, in one file, `ledger.py`, using
only the standard library. Write pytest tests for it in `tests/`.

## Milestone 1: entries

- `Ledger()` makes an empty ledger.
- `ledger.add(date, amount, category, note="")` adds an expense and
  returns its id: `1` for the first, then `2`, `3` and so on. An id is
  never used twice, even after its entry is removed.
  - `date` is a string `YYYY-MM-DD` that is a real date: `2024-02-29`
    is one, `2026-02-30` and `2026-3-1` are not.
  - `amount` is a string: digits, then optionally a `.` and one or two
    more digits, such as `12`, `12.5` or `0.99`. It must be more than
    zero. It is kept as a whole number of cents: `"12.5"` is `1250`.
  - `category` is a string. Spaces at both ends are taken away and it is
    made lower case, so `" Food "` is `food`. It can't be empty after
    that.
  - `note` is any string, kept as it is.
  - Any invalid argument raises `ValueError`; then nothing is added and
    no id is used.
- `ledger.get(id)` returns the entry as a dict:
  `{"id": 1, "date": "2026-03-01", "cents": 1250, "category": "food", "note": ""}`.
  An id that isn't in the ledger raises `KeyError`.
- `ledger.remove(id)` removes the entry. An id that isn't in the ledger
  raises `KeyError`.
- `ledger.entries()` returns every entry, as such dicts, in a list
  sorted by date, then by id.
```acceptance
[{"kind": "file_exists", "path": "ledger.py"}]
```

## Milestone 2: totals

- `ledger.total(category=None, month=None)` returns the sum, in cents,
  of the entries that match both: `category` is compared as `add` keeps
  it (`" FOOD"` matches `food`), and `month` is a string `YYYY-MM` that
  matches the entries of that month. `None` matches every entry. With
  no entry matching, the total is `0`. A month that isn't `YYYY-MM` with
  a month from `01` to `12`, such as `2026-13` or `2026-3`, raises
  `ValueError`.
- `ledger.by_category(month=None)` returns a dict from each category to
  its total in cents, only for categories with at least one entry (in
  that month, when one is given), with the keys in alphabetical order.
- `format_cents(cents)`, a function of the module, writes a number of
  cents as an amount with two decimals: `1250` is `"12.50"`, `5` is
  `"0.05"`, `0` is `"0.00"`.

## Milestone 3: files

- `ledger.save(path)` writes the ledger to a JSON file: an object with
  `"next_id"`, the id the next `add` will return, and `"entries"`, the
  list `entries()` returns.
- `Ledger.load(path)` is a class method that reads such a file back into
  a new ledger with the same entries and ids. Its next `add` returns
  the saved `"next_id"`. A path where no file exists gives an empty
  ledger.
```acceptance
[{"kind": "file_contains", "path": "ledger.py", "contains": "def load"}]
```

## Milestone 4: the command line

`python ledger.py FILE COMMAND [ARGUMENTS...]` loads the ledger from
`FILE` (an empty one when it doesn't exist), runs one command, and,
when the command changed the ledger, saves it back to `FILE`.

- `add DATE AMOUNT CATEGORY [NOTE...]`: adds an expense and prints its
  id. The note is every argument after the category, joined with one
  space; with none, it is empty.
- `remove ID`: removes the entry. Prints nothing.
- `list`: prints one line per entry, in the order of `entries()`, with
  five fields separated by a tab: id, date, amount (as `format_cents`
  writes it), category and note. Prints nothing when the ledger is
  empty.
- `report [MONTH]`: prints one line per category, in alphabetical
  order, with the category and its total (as `format_cents` writes it)
  separated by a tab, then a last line `total`, a tab, and the total of
  all of them. With a `MONTH` (`YYYY-MM`), only the entries of that
  month count, and categories with none in that month are left out.
  With no entry, it prints only `total` and `0.00`.

When the command works, the program exits with code 0. Anything wrong,
such as a `FILE` with no command, an unknown command, a missing
argument, an invalid value or an id that isn't in the ledger, prints one
line starting with `Error:` to standard error, exits with code 1, and
leaves `FILE` as it was. With no arguments at all, it prints a line
starting with `usage:` to standard error and exits with code 2.
```acceptance
[{"kind": "file_contains", "path": "ledger.py", "contains": "__main__"}]
```
