"""Tests for certo.task_store.

`MemoryTaskStore` and `SQLTaskStore` (via a real sqlite temp file — no
external service needed, matches `mysql`/`postgres` byte-for-byte since
all three share the same implementation, see the module docstring) are
tested fully here, no LLM/network. `RedisTaskStore` starts a real
`redis-server` subprocess on an ephemeral port when the binary is
installed (same "skip-if-missing marker" convention as
`tests/custom_tools/test_run_tests_tool.py`'s go/cargo/npm tests) and is
skipped cleanly otherwise.

`mysql`/`postgres` specifically were verified live during development
against real `mysql:8`/`postgres:16-alpine` Docker containers (see
DECISIONS.md) but are not run as part of the automated
suite, since that would require Docker (or a live server) in every
environment `uv run pytest -q` runs in — they exercise the exact same
`SQLTaskStore` code path the sqlite tests already cover in full.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time

import pytest

from certo.task_store import (
    MemoryTaskStore,
    SQLTaskStore,
    TaskRecord,
    _build_sql_url,
    build_task_store,
)


def _cfg(**overrides):
    from certo.config import Config

    base = {
        "model": "openai/gpt-4o",
        "api_key": "key",
        "base_url": None,
        "workspace": ".",
        "max_iterations": 10,
        "confirm_mode": "never",
        "execution": "local",
    }
    base.update(overrides)
    return Config(**base)


# --- TaskRecord round-tripping (used by RedisTaskStore's JSON encoding) ----


def test_task_record_round_trips_through_json_dict():
    record = TaskRecord(
        id="t1",
        task="do something",
        status="completed",
        project="myapp",
        messages=[{"role": "assistant", "content": "hi"}],
        verification_state="verified",
        completion_contract={
            "goal": "x",
            "acceptance_criteria": [],
            "verification_checks": [],
            "limitations": [],
        },
        acceptance_results=[{"passed": True}],
    )

    restored = TaskRecord.from_json_dict(record.to_json_dict())

    assert restored == record


# --- MemoryTaskStore ---------------------------------------------------------


def test_memory_store_save_and_get():
    store = MemoryTaskStore()
    record = TaskRecord(id="t1", task="do something", project="myapp")

    store.save(record)

    assert store.get("t1") == record


def test_memory_store_get_missing_returns_none():
    store = MemoryTaskStore()
    assert store.get("does-not-exist") is None


def test_memory_store_save_upserts():
    store = MemoryTaskStore()
    record = TaskRecord(id="t1", task="do something", status="pending")
    store.save(record)

    record.status = "completed"
    store.save(record)

    assert store.get("t1").status == "completed"


def test_memory_store_delete():
    store = MemoryTaskStore()
    store.save(TaskRecord(id="t1", task="x"))

    assert store.delete("t1") is True
    assert store.get("t1") is None
    assert store.delete("t1") is False  # already gone


def test_memory_store_delete_by_project():
    store = MemoryTaskStore()
    store.save(TaskRecord(id="t1", task="x", project="myapp"))
    store.save(TaskRecord(id="t2", task="y", project="myapp"))
    store.save(TaskRecord(id="t3", task="z", project="other"))

    deleted = store.delete_by_project("myapp")

    assert deleted == 2
    assert store.get("t1") is None
    assert store.get("t2") is None
    assert store.get("t3") is not None


def test_memory_store_delete_by_project_unknown_returns_zero():
    store = MemoryTaskStore()
    assert store.delete_by_project("nope") == 0


def test_memory_store_purge_expired_ignores_ttl_zero():
    store = MemoryTaskStore()
    store.save(TaskRecord(id="t1", task="x", status="completed", updated_at=0.0))

    assert store.purge_expired(0) == 0
    assert store.get("t1") is not None


def test_memory_store_purge_expired_only_purges_terminal_states():
    store = MemoryTaskStore()
    old_time = time.time() - 1000
    store.save(TaskRecord(id="done", task="x", status="completed", updated_at=old_time))
    store.save(TaskRecord(id="failed", task="x", status="failed", updated_at=old_time))
    store.save(TaskRecord(id="running", task="x", status="running", updated_at=old_time))
    store.save(TaskRecord(id="pending", task="x", status="pending", updated_at=old_time))
    store.save(TaskRecord(id="fresh", task="x", status="completed", updated_at=time.time()))

    purged = store.purge_expired(500)

    assert purged == 2
    assert store.get("done") is None
    assert store.get("failed") is None
    assert store.get("running") is not None
    assert store.get("pending") is not None
    assert store.get("fresh") is not None


# --- SQLTaskStore (via a real sqlite file — no external service needed) ----


@pytest.fixture
def sqlite_store(tmp_path):
    store = SQLTaskStore(f"sqlite:///{tmp_path / 'tasks.db'}")
    yield store
    store.close()


def test_sql_store_save_and_get(sqlite_store):
    record = TaskRecord(id="t1", task="do something", project="myapp")

    sqlite_store.save(record)
    got = sqlite_store.get("t1")

    assert got == record


def test_sql_store_get_missing_returns_none(sqlite_store):
    assert sqlite_store.get("does-not-exist") is None


def test_sql_store_save_upserts_not_duplicates(sqlite_store):
    record = TaskRecord(id="t1", task="do something", status="pending")
    sqlite_store.save(record)

    record.status = "running"
    record.messages.append({"role": "assistant", "content": "hi"})
    sqlite_store.save(record)

    got = sqlite_store.get("t1")
    assert got.status == "running"
    assert got.messages == [{"role": "assistant", "content": "hi"}]


def test_sql_store_preserves_nested_json_fields(sqlite_store):
    record = TaskRecord(
        id="t1",
        task="x",
        completion_contract={
            "goal": "g",
            "acceptance_criteria": ["a"],
            "verification_checks": [],
            "limitations": [],
        },
        acceptance_results=[{"passed": False, "detail": "nope"}],
    )

    sqlite_store.save(record)
    got = sqlite_store.get("t1")

    assert got.completion_contract == record.completion_contract
    assert got.acceptance_results == record.acceptance_results


def test_sql_store_delete(sqlite_store):
    sqlite_store.save(TaskRecord(id="t1", task="x"))

    assert sqlite_store.delete("t1") is True
    assert sqlite_store.get("t1") is None
    assert sqlite_store.delete("t1") is False


def test_sql_store_delete_by_project(sqlite_store):
    sqlite_store.save(TaskRecord(id="t1", task="x", project="myapp"))
    sqlite_store.save(TaskRecord(id="t2", task="y", project="myapp"))
    sqlite_store.save(TaskRecord(id="t3", task="z", project="other"))

    deleted = sqlite_store.delete_by_project("myapp")

    assert deleted == 2
    assert sqlite_store.get("t1") is None
    assert sqlite_store.get("t3") is not None


def test_sql_store_purge_expired_ignores_ttl_zero(sqlite_store):
    sqlite_store.save(TaskRecord(id="t1", task="x", status="completed", updated_at=0.0))
    assert sqlite_store.purge_expired(0) == 0
    assert sqlite_store.get("t1") is not None


def test_sql_store_purge_expired_only_purges_terminal_states(sqlite_store):
    old_time = time.time() - 1000
    sqlite_store.save(TaskRecord(id="done", task="x", status="completed", updated_at=old_time))
    sqlite_store.save(TaskRecord(id="running", task="x", status="running", updated_at=old_time))
    sqlite_store.save(TaskRecord(id="fresh", task="x", status="completed", updated_at=time.time()))

    purged = sqlite_store.purge_expired(500)

    assert purged == 1
    assert sqlite_store.get("done") is None
    assert sqlite_store.get("running") is not None
    assert sqlite_store.get("fresh") is not None


# --- _build_sql_url: pure string construction, no live connection needed --


def test_build_sql_url_sqlite():
    cfg = _cfg(task_store="sqlite", task_store_sqlite_path="./tasks.db")
    assert _build_sql_url(cfg) == "sqlite:///./tasks.db"


def test_build_sql_url_mysql_without_password():
    cfg = _cfg(
        task_store="mysql",
        task_store_mysql_host="db.internal",
        task_store_mysql_port=3307,
        task_store_mysql_user="certo",
        task_store_mysql_password=None,
        task_store_mysql_database="certo_prod",
    )
    assert _build_sql_url(cfg) == "mysql+pymysql://certo@db.internal:3307/certo_prod"


def test_build_sql_url_mysql_with_password():
    cfg = _cfg(
        task_store="mysql",
        task_store_mysql_user="certo",
        task_store_mysql_password="secret",
        task_store_mysql_host="db.internal",
        task_store_mysql_port=3306,
        task_store_mysql_database="certo_prod",
    )
    assert _build_sql_url(cfg) == "mysql+pymysql://certo:secret@db.internal:3306/certo_prod"


def test_build_sql_url_postgres_with_password():
    cfg = _cfg(
        task_store="postgres",
        task_store_postgres_user="certo",
        task_store_postgres_password="secret",
        task_store_postgres_host="pg.internal",
        task_store_postgres_port=5433,
        task_store_postgres_database="certo_prod",
    )
    assert _build_sql_url(cfg) == "postgresql+psycopg2://certo:secret@pg.internal:5433/certo_prod"


def test_build_sql_url_rejects_a_non_sql_backend():
    cfg = _cfg(task_store="memory")
    with pytest.raises(ValueError, match="non-SQL backend"):
        _build_sql_url(cfg)


# --- build_task_store: the one factory server.py/admin_cli.py both use ----


def test_build_task_store_memory_returns_memory_store():
    store = build_task_store(_cfg(task_store="memory"))
    assert isinstance(store, MemoryTaskStore)


def test_build_task_store_sqlite_returns_sql_store(tmp_path):
    cfg = _cfg(task_store="sqlite", task_store_sqlite_path=str(tmp_path / "tasks.db"))
    store = build_task_store(cfg)
    try:
        assert isinstance(store, SQLTaskStore)
    finally:
        store.close()


def test_build_task_store_rejects_an_unknown_backend():
    cfg = _cfg(task_store="memory")
    object.__setattr__(cfg, "task_store", "oracle")  # bypass Config's own validation
    with pytest.raises(ValueError, match="Unsupported CERTO_TASK_STORE"):
        build_task_store(cfg)


# --- RedisTaskStore: a real redis-server subprocess, skipped if missing ----

_requires_redis_server = pytest.mark.skipif(
    shutil.which("redis-server") is None, reason="redis-server not installed"
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def redis_store():
    port = _free_port()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--daemonize", "no", "--save", ""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from certo.task_store import RedisTaskStore

        store = None
        for _ in range(50):
            try:
                store = RedisTaskStore(
                    host="localhost", port=port, db=0, password=None, use_tls=False
                )
                store._redis.ping()
                break
            except Exception:  # noqa: BLE001 - retry until the server is ready
                time.sleep(0.1)
        assert store is not None, "redis-server never became ready"
        yield store
        store.close()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@_requires_redis_server
def test_redis_store_save_and_get(redis_store):
    record = TaskRecord(id="t1", task="do something", project="myapp")
    redis_store.save(record)

    assert redis_store.get("t1") == record


@_requires_redis_server
def test_redis_store_get_missing_returns_none(redis_store):
    assert redis_store.get("does-not-exist") is None


@_requires_redis_server
def test_redis_store_delete(redis_store):
    redis_store.save(TaskRecord(id="t1", task="x"))

    assert redis_store.delete("t1") is True
    assert redis_store.get("t1") is None
    assert redis_store.delete("t1") is False


@_requires_redis_server
def test_redis_store_delete_by_project(redis_store):
    redis_store.save(TaskRecord(id="t1", task="x", project="myapp"))
    redis_store.save(TaskRecord(id="t2", task="y", project="myapp"))
    redis_store.save(TaskRecord(id="t3", task="z", project="other"))

    deleted = redis_store.delete_by_project("myapp")

    assert deleted == 2
    assert redis_store.get("t1") is None
    assert redis_store.get("t3") is not None


@_requires_redis_server
def test_redis_store_purge_expired_is_a_documented_noop(redis_store):
    # Native per-key TTL (set in save()) handles expiry — see the class
    # docstring for why purge_expired() is deliberately inert here.
    redis_store.save(TaskRecord(id="t1", task="x", status="completed"))
    assert redis_store.purge_expired(1) == 0
    assert redis_store.get("t1") is not None


@_requires_redis_server
def test_redis_store_sets_native_ttl_only_for_terminal_status(redis_store):
    from certo.task_store import RedisTaskStore

    ttl_store = RedisTaskStore(
        host=redis_store._redis.connection_pool.connection_kwargs["host"],
        port=redis_store._redis.connection_pool.connection_kwargs["port"],
        db=0,
        password=None,
        use_tls=False,
        ttl_seconds=100,
    )
    try:
        record = TaskRecord(id="t1", task="x", status="running")
        ttl_store.save(record)
        assert ttl_store._redis.ttl("certo:task:t1") == -1  # no expiration while running

        record.status = "completed"
        ttl_store.save(record)
        ttl = ttl_store._redis.ttl("certo:task:t1")
        assert 0 < ttl <= 100
    finally:
        ttl_store.close()


@_requires_redis_server
def test_redis_store_expires_a_completed_record_via_native_ttl(redis_store):
    from certo.task_store import RedisTaskStore

    ttl_store = RedisTaskStore(
        host=redis_store._redis.connection_pool.connection_kwargs["host"],
        port=redis_store._redis.connection_pool.connection_kwargs["port"],
        db=0,
        password=None,
        use_tls=False,
        ttl_seconds=1,
    )
    try:
        ttl_store.save(TaskRecord(id="t1", task="x", status="completed"))
        assert ttl_store.get("t1") is not None
        time.sleep(1.5)
        assert ttl_store.get("t1") is None
    finally:
        ttl_store.close()


# --- Pre-rename (harness_*) storage names are still read --------------------


def test_sql_store_new_database_uses_certo_tasks_table(tmp_path):
    import sqlalchemy as sa

    url = f"sqlite:///{tmp_path / 'tasks.db'}"
    SQLTaskStore(url).close()
    assert sa.inspect(sa.create_engine(url)).get_table_names() == ["certo_tasks"]


def test_sql_store_keeps_using_an_existing_legacy_table(tmp_path):
    import sqlalchemy as sa

    url = f"sqlite:///{tmp_path / 'tasks.db'}"
    store = SQLTaskStore(url)
    store.save(TaskRecord(id="old", task="before the rename", project="p"))
    store.close()
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE certo_tasks RENAME TO harness_tasks"))
    engine.dispose()

    store = SQLTaskStore(url)
    try:
        assert store.get("old").task == "before the rename"
        store.save(TaskRecord(id="new", task="after"))
        assert store.get("new") is not None
    finally:
        store.close()
    assert sa.inspect(sa.create_engine(url)).get_table_names() == ["harness_tasks"]


def test_default_sqlite_path_falls_back_to_legacy_file_when_only_it_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _cfg(task_store="sqlite", task_store_sqlite_path="./certo_tasks.db")

    assert _build_sql_url(cfg) == "sqlite:///./certo_tasks.db"  # neither exists

    (tmp_path / "harness_tasks.db").touch()
    assert _build_sql_url(cfg) == "sqlite:///./harness_tasks.db"

    (tmp_path / "certo_tasks.db").touch()
    assert _build_sql_url(cfg) == "sqlite:///./certo_tasks.db"  # new one wins


def test_explicit_sqlite_path_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "harness_tasks.db").touch()
    cfg = _cfg(task_store="sqlite", task_store_sqlite_path="./mine.db")
    assert _build_sql_url(cfg) == "sqlite:///./mine.db"


@_requires_redis_server
def test_redis_store_reads_and_migrates_legacy_keys(redis_store):
    import json

    r = redis_store._redis
    legacy = TaskRecord(id="old", task="before the rename", project="p")
    r.set("harness:task:old", json.dumps(legacy.to_json_dict()))
    r.sadd("harness:project:p", "old")

    assert redis_store.get("old") == legacy

    legacy.status = "completed"
    redis_store.save(legacy)
    assert r.exists("harness:task:old") == 0
    assert r.exists("certo:task:old") == 1
    assert r.smembers("harness:project:p") == set()
    assert r.smembers("certo:project:p") == {"old"}


@_requires_redis_server
def test_redis_store_deletes_cover_legacy_keys(redis_store):
    import json

    r = redis_store._redis
    for task_id in ("a", "b"):
        rec = TaskRecord(id=task_id, task="x", project="p")
        r.set(f"harness:task:{task_id}", json.dumps(rec.to_json_dict()))
        r.sadd("harness:project:p", task_id)
    redis_store.save(TaskRecord(id="c", task="x", project="p"))

    assert redis_store.delete("a") is True
    assert r.exists("harness:task:a") == 0
    assert redis_store.delete_by_project("p") == 2
    assert r.keys("*") == []


# --- the rungs column (escalation) ----------------------------------------------------


def test_sql_store_keeps_an_escalations_rungs(sqlite_store):
    rungs = [{"rung": 1, "name": "local", "verdict": "no_progress", "final": False}]
    sqlite_store.save(TaskRecord(id="t1", task="x", rungs=rungs))
    assert sqlite_store.get("t1").rungs == rungs


def test_sql_store_adds_the_rungs_column_to_an_older_table(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE certo_tasks (id VARCHAR(64) PRIMARY KEY, task TEXT NOT NULL, "
            "status VARCHAR(32) NOT NULL, project VARCHAR(255), messages TEXT NOT NULL, "
            "error TEXT, created_at FLOAT NOT NULL, updated_at FLOAT NOT NULL, "
            "verification_state VARCHAR(64), completion_contract TEXT, acceptance_results TEXT)"
        )
        conn.execute(
            "INSERT INTO certo_tasks VALUES ('old', 'x', 'completed', NULL, '[]', NULL, 1, 1, "
            "'verified', NULL, NULL)"
        )

    store = SQLTaskStore(f"sqlite:///{path}")

    assert store.get("old").rungs is None
    store.save(TaskRecord(id="new", task="y", rungs=[{"rung": 1}]))
    assert store.get("new").rungs == [{"rung": 1}]
    assert store.get("old").result is None
    store.save(TaskRecord(id="newer", task="z", result={"verdict": "verified"}))
    assert store.get("newer").result == {"verdict": "verified"}
    store.close()


def test_a_record_saved_before_rungs_existed_still_loads():
    data = TaskRecord(id="t", task="x").to_json_dict()
    del data["rungs"]
    assert TaskRecord.from_json_dict(data).rungs is None


def test_sql_store_keeps_the_json_result(sqlite_store):
    result = {"result_version": 1, "verdict": "verified"}
    sqlite_store.save(TaskRecord(id="t1", task="x", result=result))
    assert sqlite_store.get("t1").result == result


def test_a_record_saved_before_the_result_existed_still_loads():
    data = TaskRecord(id="t", task="x").to_json_dict()
    del data["result"]
    assert TaskRecord.from_json_dict(data).result is None
