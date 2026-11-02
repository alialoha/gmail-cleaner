from pathlib import Path

import pytest
from pydantic import ValidationError

from gmail_cleaner.accounts.registry import Account, AccountRegistry
from gmail_cleaner.history.db import HistoryStore
from gmail_cleaner.paths import ensure_layout


def test_account_registry_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    home = ensure_layout()
    reg = AccountRegistry(path=home / "accounts.yaml")
    account = Account(
        id="personal",
        email="a@example.com",
        credentials_file=home / "credentials" / "client.json",
        token_file=home / "tokens" / "personal.json",
        scope="modify",
    )
    reg.add(account)
    loaded = reg.get("personal")
    assert loaded.email == "a@example.com"
    reg.remove("personal")
    assert reg.load() == []


def test_account_rejects_bad_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    home = ensure_layout()
    with pytest.raises(ValidationError):
        Account(
            id="../evil",
            email="a@example.com",
            credentials_file=home / "credentials" / "client.json",
            token_file=home / "tokens" / "x.json",
            scope="modify",
        )


def test_history_run_lifecycle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    ensure_layout()
    store = HistoryStore(path=tmp_path / "gc" / "data" / "history.db")
    run_id = store.start_run("personal", "scan")
    store.add_finding(
        run_id,
        bucket="sender",
        sender="news@example.com",
        query=None,
        message_count=3,
        est_bytes=12345,
        sample_ids=["m1", "m2"],
    )
    store.finish_run(run_id, summary={"ok": True})
    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert len(run["findings"]) == 1
