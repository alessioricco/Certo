# Team board: a task board web app with a SQLite database

Python 3.10 or newer, with FastAPI and the SQLite database built into
Python (`sqlite3`). A bigger sample, in milestones: run it with

```bash
certo --milestones tasks/team-board.md --project team-board
```

Build a web app where a team plans its work on boards: people sign up
and log in, create projects, invite each other with roles, and move cards
between columns. A JSON API, a SQLite database, and a browser interface
in plain HTML, CSS and JavaScript.

## Rules for every milestone

- Layout: a package `taskboard/` with `app.py` (the FastAPI application,
  named `app`), `db.py` (the schema and the connection), and one module
  per area (`auth.py`, `ordering.py`, `query.py`...); the browser files
  in `taskboard/static/`; tests in `tests/`.
- The database is one SQLite file, at the path in the environment
  variable `TASKBOARD_DB` (default `taskboard.db`). `db.py` creates the
  tables when they don't exist, with foreign keys on. Use SQL with `?`
  parameters, never text pasted into a query.
- The API is JSON under `/api`. Errors have the right status (400 bad
  input, 401 not logged in, 403 not allowed, 404 not found or not a
  member of the project, 409 conflict) and a JSON body
  `{"detail": "..."}` that says what is wrong.
- Dependencies (FastAPI, uvicorn, and httpx for the test client) are
  pinned in `requirements.txt`; pytest is the test runner.
- Tests use FastAPI's `TestClient` and a fresh database file in a
  temporary folder for each test, never the real one. Every example in a
  table below goes into them, copied as written: they are worked out
  already, don't change them. Each milestone adds its own tests and keeps
  the earlier ones passing.
- `README.md`: how to install, start the app
  (`uvicorn taskboard.app:app`) and run the tests.

## Milestone 1: Accounts and sessions

| Endpoint | What it does |
| --- | --- |
| `POST /api/register` `{email, name, password}` | Creates the account: 201 with `{id, email, name}`. 400 when the email isn't an email or the password is shorter than 8 characters; 409 when the email is taken (case doesn't matter). |
| `POST /api/login` `{email, password}` | 200 with the user, and sets an `HttpOnly` cookie `session`; 401 for a wrong email or password, with the same message for both. |
| `POST /api/logout` | Ends the session: 204. |
| `GET /api/me` | The logged-in user, or 401. |

Passwords are stored only as a salted hash made with `hashlib.scrypt`
(each with its own random salt), never as text. A session is a random
token (`secrets.token_urlsafe`) stored in a `sessions` table; logging out
deletes it.

```acceptance
[{"kind": "file_exists", "path": "taskboard/app.py"},
 {"kind": "file_contains", "path": "taskboard/auth.py", "contains": "scrypt"}]
```

## Milestone 2: Projects, members and roles

| Endpoint | What it does |
| --- | --- |
| `POST /api/projects` `{name}` | Creates a project: 201. Its creator is its `owner`. |
| `GET /api/projects` | The projects the user is a member of, with the user's role in each. |
| `GET /api/projects/{id}` | The project and its members. 404 for a user who isn't a member, so a project's existence isn't leaked. |
| `POST /api/projects/{id}/members` `{email, role}` | Owner only: adds an existing user as `member` or `viewer`. 404 for an unknown email, 409 when already a member. |
| `DELETE /api/projects/{id}/members/{user_id}` | Owner only. A project always keeps at least one owner (409). |

A `viewer` can read everything in the project and change nothing (403 on
every change, here and in the later milestones). A `member` can change
the board but not the members.

```acceptance
[{"kind": "file_contains", "path": "taskboard/app.py", "contains": "/members"}]
```

## Milestone 3: Columns and cards

A project has ordered columns (for example To do, Doing, Done), and each
column has ordered cards. A card has a title, a description, an optional
due date (`YYYY-MM-DD`), an optional assignee (a member of the project),
and labels (short words).

| Endpoint | What it does |
| --- | --- |
| `GET /api/projects/{id}/board` | The columns in order, each with its cards in order. |
| `POST /api/projects/{id}/columns` `{name}` | Adds a column at the end. |
| `PATCH /api/columns/{id}` `{name?, index?}` | Renames a column, or moves it to position `index`. |
| `POST /api/columns/{id}/cards` `{title, description?, due?, assignee_id?, labels?}` | Adds a card at the bottom of the column. 400 for an empty title, a bad date, or an assignee who isn't a member. |
| `PATCH /api/cards/{id}` | Changes any of those fields. |
| `POST /api/cards/{id}/move` `{column_id, index}` | Moves a card to position `index` of a column (the same or another one of the project). |
| `DELETE /api/cards/{id}` | Deletes a card. |

Positions are kept in the database, with no gaps or repeats after any
move. `ordering.py` has `reorder(ids, card_id, index)`: the list of ids
in a column after moving `card_id` to position `index`; an `index` past
the end means the end.

| Function | Examples |
| --- | --- |
| `reorder(ids, card_id, index)` | `reorder([1, 2, 3, 4], 4, 0)` → `[4, 1, 2, 3]`; `reorder([1, 2, 3], 1, 2)` → `[2, 3, 1]`; `reorder([1, 2, 3], 2, 9)` → `[1, 3, 2]`; `reorder([5], 5, 0)` → `[5]` |

```acceptance
[{"kind": "file_contains", "path": "taskboard/ordering.py", "contains": "def reorder"}]
```

## Milestone 4: Comments, history and search

| Endpoint | What it does |
| --- | --- |
| `GET /api/cards/{id}/comments`, `POST` `{text}` | A card's comments, oldest first, each with its author and time; viewers can read but not post. |
| `GET /api/projects/{id}/activity` | The project's history, newest first: who did what, to which card or column, and when. Every change made through the API in milestones 2 to 4 adds an entry. |
| `GET /api/projects/{id}/cards?q=...` | The cards matching a search. |

A search is words, plus filters: `label:NAME`, `assignee:NAME` (the start
of a member's name, case not mattering) and `due<YYYY-MM-DD` (due before
that date). The words match the title or description, case not mattering.
`query.py` has `parse_query(q)`, which splits a search into its parts:

| Function | Examples |
| --- | --- |
| `parse_query(q)` | `parse_query("login bug label:urgent assignee:ana due<2026-12-01")` → `{"text": "login bug", "label": "urgent", "assignee": "ana", "due_before": "2026-12-01"}`; `parse_query("label:ui")` → `{"text": "", "label": "ui"}`; `parse_query("  export   csv ")` → `{"text": "export csv"}` |

```acceptance
[{"kind": "file_contains", "path": "taskboard/query.py", "contains": "def parse_query"}]
```

## Milestone 5: The web interface

`GET /` serves `taskboard/static/index.html`, a single page in plain
HTML, CSS and JavaScript (no build step, no framework from the internet)
that uses only the API:

- sign up, log in and log out;
- the list of the user's projects, and creating one;
- a project's board: its columns side by side, cards that can be dragged
  within a column and to another one (calling the move endpoint), adding
  and renaming columns and cards;
- a card's dialog: every field, its labels, its comments, and a delete
  button with a confirmation;
- the members panel for owners (invite with a role, remove);
- the search box with its filters, and the activity list;
- what a viewer can't change is shown read-only;
- overdue cards stand out; it works on a phone-sized screen and a wide one.

Add tests that `GET /` returns the page and that the page's script and
stylesheet are served.

```acceptance
[{"kind": "file_exists", "path": "taskboard/static/index.html"},
 {"kind": "file_contains", "path": "README.md", "contains": "uvicorn"}]
```
