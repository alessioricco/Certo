# Library loans

Build a small Python library-loan system, `library.py`, with pytest tests.

- Books: add a book (id, title, copies), list books, find by title word.
- Members: register a member (id, name), with a limit of 3 loans each.
- Loans: lend a copy to a member (refuse when no copy is left or the member
  is at the limit), return it, and list a member's loans.
- Due dates: a loan is due 14 days after it starts; list overdue loans for a
  given date, and compute a fine of 0.25 per day overdue on return.
- Persistence: save everything to a JSON file and load it back.

Each part needs its own tests.
