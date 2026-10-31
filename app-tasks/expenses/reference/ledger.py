"""An expense ledger: entries, totals, JSON files and a command line."""

import datetime
import json
import re
import sys
from pathlib import Path

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_AMOUNT = re.compile(r"(\d+)(?:\.(\d{1,2}))?")
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def format_cents(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def _date(text):
    if not isinstance(text, str) or not _DATE.fullmatch(text):
        raise ValueError(f"not a date: {text!r}")
    datetime.date.fromisoformat(text)  # raises ValueError for 2026-02-30
    return text


def _cents(text):
    match = _AMOUNT.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise ValueError(f"not an amount: {text!r}")
    whole, decimals = match.group(1), match.group(2) or ""
    cents = int(whole) * 100 + int(decimals.ljust(2, "0"))
    if cents <= 0:
        raise ValueError("an amount must be more than zero")
    return cents


def _category(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a category can't be empty")
    return text.strip().lower()


def _month(text):
    if text is not None and (not isinstance(text, str) or not _MONTH.fullmatch(text)):
        raise ValueError(f"not a month: {text!r}")
    return text


class Ledger:
    def __init__(self):
        self._entries = {}
        self._next_id = 1

    def add(self, date, amount, category, note=""):
        entry = {
            "id": self._next_id,
            "date": _date(date),
            "cents": _cents(amount),
            "category": _category(category),
            "note": note,
        }
        self._entries[entry["id"]] = entry
        self._next_id += 1
        return entry["id"]

    def get(self, entry_id):
        return dict(self._entries[entry_id])

    def remove(self, entry_id):
        del self._entries[entry_id]

    def entries(self):
        ordered = sorted(self._entries.values(), key=lambda e: (e["date"], e["id"]))
        return [dict(e) for e in ordered]

    def _matching(self, category=None, month=None):
        month = _month(month)
        category = _category(category) if category is not None else None
        for entry in self.entries():
            if category is not None and entry["category"] != category:
                continue
            if month is not None and not entry["date"].startswith(month + "-"):
                continue
            yield entry

    def total(self, category=None, month=None):
        return sum(e["cents"] for e in self._matching(category, month))

    def by_category(self, month=None):
        totals = {}
        for entry in self._matching(month=month):
            totals[entry["category"]] = totals.get(entry["category"], 0) + entry["cents"]
        return dict(sorted(totals.items()))

    def save(self, path):
        data = {"next_id": self._next_id, "entries": self.entries()}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        ledger = cls()
        if not Path(path).exists():
            return ledger
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in data["entries"]:
            ledger._entries[entry["id"]] = dict(entry)
        ledger._next_id = data["next_id"]
        return ledger


def _run(ledger, command, args):
    """Run one command; return the lines to print and whether it changed
    the ledger."""
    if command == "add":
        if len(args) < 3:
            raise ValueError("add needs DATE AMOUNT CATEGORY")
        entry_id = ledger.add(args[0], args[1], args[2], " ".join(args[3:]))
        return [str(entry_id)], True
    if command == "remove":
        if len(args) != 1 or not args[0].isdigit():
            raise ValueError("remove needs one ID")
        ledger.remove(int(args[0]))
        return [], True
    if command == "list":
        lines = [
            "\t".join([str(e["id"]), e["date"], format_cents(e["cents"]), e["category"], e["note"]])
            for e in ledger.entries()
        ]
        return lines, False
    if command == "report":
        if len(args) > 1:
            raise ValueError("report takes at most one MONTH")
        month = args[0] if args else None
        totals = ledger.by_category(month)
        lines = [f"{name}\t{format_cents(cents)}" for name, cents in totals.items()]
        lines.append(f"total\t{format_cents(sum(totals.values()))}")
        return lines, False
    raise ValueError(f"unknown command: {command!r}")


def main(argv):
    if not argv:
        print("usage: ledger.py FILE COMMAND [ARGUMENTS...]", file=sys.stderr)
        return 2
    if len(argv) < 2:
        print("Error: no command", file=sys.stderr)
        return 1
    path, command, args = argv[0], argv[1], argv[2:]
    try:
        ledger = Ledger.load(path)
        lines, changed = _run(ledger, command, args)
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if changed:
        ledger.save(path)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
