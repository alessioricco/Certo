"""The expense ledger, milestones 1 to 3: every rule the task states.
Test names start with their milestone (m1_ to m3_)."""

import json

import pytest
from ledger import Ledger, format_cents


def ledger_with(*entries):
    ledger = Ledger()
    for entry in entries:
        ledger.add(*entry)
    return ledger


# --- milestone 1: entries ---------------------------------------------------


def test_m1_ids_start_at_one_and_go_up():
    ledger = Ledger()
    assert ledger.add("2026-03-01", "12.50", "food") == 1
    assert ledger.add("2026-03-02", "3", "bus") == 2
    assert ledger.add("2026-03-02", "4", "bus") == 3


def test_m1_get_returns_the_entry_as_a_dict():
    ledger = Ledger()
    ledger.add("2026-03-01", "12.5", " Food ", "lunch with Ana")
    assert ledger.get(1) == {
        "id": 1,
        "date": "2026-03-01",
        "cents": 1250,
        "category": "food",
        "note": "lunch with Ana",
    }


def test_m1_the_note_is_empty_by_default():
    ledger = ledger_with(("2026-03-01", "1", "food"))
    assert ledger.get(1)["note"] == ""


@pytest.mark.parametrize(
    ("amount", "cents"),
    [("12", 1200), ("12.5", 1250), ("12.50", 1250), ("0.99", 99), ("0.5", 50), ("1000", 100000)],
)
def test_m1_amounts_are_kept_in_cents(amount, cents):
    ledger = ledger_with(("2026-03-01", amount, "food"))
    cents_kept = ledger.get(1)["cents"]
    assert cents_kept == cents
    assert type(cents_kept) is int


@pytest.mark.parametrize("amount", ["0", "0.00", "-5", "12.345", "abc", "1,50", "", "12."])
def test_m1_an_invalid_amount_raises(amount):
    with pytest.raises(ValueError):
        Ledger().add("2026-03-01", amount, "food")


@pytest.mark.parametrize(
    "date", ["2026-02-30", "2026-3-1", "2026-13-01", "01-03-2026", "", "today"]
)
def test_m1_an_invalid_date_raises(date):
    with pytest.raises(ValueError):
        Ledger().add(date, "1", "food")


def test_m1_a_leap_day_is_a_date():
    ledger = ledger_with(("2024-02-29", "1", "food"))
    assert ledger.get(1)["date"] == "2024-02-29"


@pytest.mark.parametrize("category", ["", "   "])
def test_m1_an_empty_category_raises(category):
    with pytest.raises(ValueError):
        Ledger().add("2026-03-01", "1", category)


def test_m1_categories_are_trimmed_and_lower_case():
    ledger = ledger_with(("2026-03-01", "1", "  Rent  "), ("2026-03-01", "1", "BUS"))
    assert [e["category"] for e in ledger.entries()] == ["rent", "bus"]


def test_m1_a_failed_add_adds_nothing_and_uses_no_id():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.add("2026-03-01", "0", "food")
    assert ledger.entries() == []
    assert ledger.add("2026-03-01", "1", "food") == 1


def test_m1_get_of_an_unknown_id_raises_key_error():
    ledger = ledger_with(("2026-03-01", "1", "food"))
    with pytest.raises(KeyError):
        ledger.get(2)


def test_m1_remove_takes_the_entry_away():
    ledger = ledger_with(("2026-03-01", "1", "food"), ("2026-03-02", "2", "bus"))
    ledger.remove(1)
    assert [e["id"] for e in ledger.entries()] == [2]
    with pytest.raises(KeyError):
        ledger.get(1)


def test_m1_remove_of_an_unknown_id_raises_key_error():
    ledger = ledger_with(("2026-03-01", "1", "food"))
    ledger.remove(1)
    with pytest.raises(KeyError):
        ledger.remove(1)


def test_m1_an_id_is_never_used_twice():
    ledger = ledger_with(("2026-03-01", "1", "food"), ("2026-03-02", "2", "bus"))
    ledger.remove(2)
    assert ledger.add("2026-03-03", "3", "food") == 3


def test_m1_entries_are_sorted_by_date_then_id():
    ledger = ledger_with(
        ("2026-03-05", "1", "a"),
        ("2026-02-28", "2", "b"),
        ("2026-03-05", "3", "c"),
        ("2025-12-31", "4", "d"),
    )
    assert [e["id"] for e in ledger.entries()] == [4, 2, 1, 3]


def test_m1_entries_of_an_empty_ledger_is_an_empty_list():
    assert Ledger().entries() == []


def test_m1_entries_are_dicts_with_every_field():
    ledger = ledger_with(("2026-03-01", "2.05", "Food", "x"))
    assert ledger.entries() == [
        {"id": 1, "date": "2026-03-01", "cents": 205, "category": "food", "note": "x"}
    ]


# --- milestone 2: totals ----------------------------------------------------


def sample():
    return ledger_with(
        ("2026-02-27", "10", "food"),
        ("2026-03-01", "12.50", "food"),
        ("2026-03-02", "2.25", "bus"),
        ("2026-03-31", "800", "rent"),
        ("2026-04-01", "3", "Bus"),
    )


def test_m2_total_of_everything():
    assert sample().total() == 1000 + 1250 + 225 + 80000 + 300


def test_m2_total_of_a_category():
    assert sample().total(category="bus") == 525


def test_m2_a_category_is_compared_as_add_keeps_it():
    assert sample().total(category=" BUS ") == 525


def test_m2_total_of_a_month():
    assert sample().total(month="2026-03") == 1250 + 225 + 80000


def test_m2_total_of_a_category_in_a_month():
    assert sample().total(category="food", month="2026-03") == 1250


def test_m2_total_with_nothing_matching_is_zero():
    ledger = sample()
    assert ledger.total(category="travel") == 0
    assert ledger.total(month="2025-01") == 0
    assert Ledger().total() == 0


@pytest.mark.parametrize("month", ["2026-13", "2026-3", "2026-00", "2026", "march", "2026-03-01"])
def test_m2_an_invalid_month_raises(month):
    with pytest.raises(ValueError):
        sample().total(month=month)


def test_m2_by_category_in_alphabetical_order():
    totals = sample().by_category()
    assert totals == {"bus": 525, "food": 2250, "rent": 80000}
    assert list(totals) == ["bus", "food", "rent"]


def test_m2_by_category_of_a_month_leaves_out_the_others():
    totals = sample().by_category(month="2026-04")
    assert totals == {"bus": 300}


def test_m2_by_category_of_an_empty_ledger():
    assert Ledger().by_category() == {}


def test_m2_by_category_with_an_invalid_month_raises():
    with pytest.raises(ValueError):
        sample().by_category(month="2026-3")


def test_m2_removed_entries_no_longer_count():
    ledger = sample()
    ledger.remove(4)
    assert ledger.total() == 1000 + 1250 + 225 + 300
    assert "rent" not in ledger.by_category()


@pytest.mark.parametrize(
    ("cents", "text"),
    [(1250, "12.50"), (5, "0.05"), (0, "0.00"), (100, "1.00"), (99, "0.99"), (123456, "1234.56")],
)
def test_m2_format_cents(cents, text):
    assert format_cents(cents) == text


# --- milestone 3: files -----------------------------------------------------


def test_m3_save_writes_next_id_and_the_entries(tmp_path):
    ledger = sample()
    ledger.remove(5)
    path = tmp_path / "ledger.json"
    ledger.save(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["next_id"] == 6
    assert data["entries"] == ledger.entries()


def test_m3_load_gives_the_same_entries(tmp_path):
    ledger = sample()
    path = tmp_path / "ledger.json"
    ledger.save(str(path))
    loaded = Ledger.load(str(path))
    assert loaded.entries() == ledger.entries()
    assert loaded.get(2) == ledger.get(2)
    assert loaded.total(month="2026-03") == ledger.total(month="2026-03")


def test_m3_load_continues_the_ids(tmp_path):
    ledger = sample()
    ledger.remove(5)
    path = tmp_path / "ledger.json"
    ledger.save(str(path))
    assert Ledger.load(str(path)).add("2026-05-01", "1", "food") == 6


def test_m3_an_empty_ledger_saves_and_loads(tmp_path):
    path = tmp_path / "ledger.json"
    Ledger().save(str(path))
    loaded = Ledger.load(str(path))
    assert loaded.entries() == []
    assert loaded.add("2026-05-01", "1", "food") == 1


def test_m3_load_of_a_missing_file_is_an_empty_ledger(tmp_path):
    loaded = Ledger.load(str(tmp_path / "nothing-here.json"))
    assert loaded.entries() == []
    assert loaded.add("2026-05-01", "1", "food") == 1


def test_m3_a_saved_note_with_any_text_comes_back(tmp_path):
    ledger = ledger_with(("2026-03-01", "1", "food", 'café, "quoted"\tand tabs'))
    path = tmp_path / "ledger.json"
    ledger.save(str(path))
    assert Ledger.load(str(path)).get(1)["note"] == 'café, "quoted"\tand tabs'
