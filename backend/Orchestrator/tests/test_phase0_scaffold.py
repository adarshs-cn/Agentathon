"""PHASE 0 integration test: the workspace imports cleanly and the database layer works."""
import importlib
import pkgutil

import pytest

import orchestrator
from orchestrator import config
from orchestrator.stores.db import TABLES, Database


def test_every_package_imports():
    """Every module under orchestrator/ must import (catches broken __init__ and cycles)."""
    failures = []
    for m in pkgutil.walk_packages(orchestrator.__path__, "orchestrator."):
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            failures.append((m.name, repr(e)))
    assert not failures, failures


def test_config_is_sane():
    assert set(config.CHANNELS) == {"whatsapp", "email", "voice"}
    for purpose, prefs in config.CHANNEL_PREFERENCE.items():
        assert purpose in config.PURPOSES
        assert prefs and set(prefs) <= set(config.CHANNELS)
    assert config.Policy().per_borrower_daily_cap == 1


def test_schema_created():
    db = Database(":memory:")
    names = {r["name"] for r in db.query("select name from sqlite_master where type='table'")}
    assert set(TABLES) <= names


def test_transaction_rolls_back_on_error():
    db = Database(":memory:")
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("insert into customer_profile values ('X', 1, 0, '[]')")
            raise RuntimeError("boom")
    assert db.one("select * from customer_profile where customer_id='X'") is None


def test_file_database_persists_across_reopen(tmp_path):
    p = tmp_path / "t.db"
    db = Database(p)
    db.execute("insert into customer_profile values ('B1', 5, 0, '[]')")
    db.close()
    db2 = Database(p)
    assert db2.one("select dpd from customer_profile where customer_id='B1'")["dpd"] == 5


def test_event_queue_rejects_duplicate_event_id():
    import sqlite3
    db = Database(":memory:")
    db.execute("insert into event_queue(event_id,account_id,type,event_time) values ('e1','B1','DUE_SOON','t')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into event_queue(event_id,account_id,type,event_time) values ('e1','B1','DUE_SOON','t')")
