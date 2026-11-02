from pathlib import Path

import pytest

from gmail_cleaner.paths import (
    ensure_layout,
    token_path_for,
    validate_account_id,
    write_secret_file,
)
from gmail_cleaner.policy.models import Policy, load_policy
from gmail_cleaner.report.builder import format_bytes


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.00 KB"
    assert "MB" in format_bytes(5 * 1024 * 1024)


def test_ensure_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    home = ensure_layout()
    assert (home / "credentials").is_dir()
    assert (home / "tokens").is_dir()
    assert (home / "data" / "reports").is_dir()


def test_default_policy() -> None:
    policy = Policy()
    names = {q.name for q in policy.enabled_queries()}
    assert "large_attachments" in names
    assert "old_promotions" in names


def test_load_policy_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    ensure_layout()
    policy = load_policy()
    assert policy.version == 1


def test_validate_account_id_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        validate_account_id("../evil")
    with pytest.raises(ValueError):
        validate_account_id("a/b")
    assert validate_account_id("personal") == "personal"
    assert validate_account_id("work_1") == "work_1"


def test_token_path_for_stays_inside_tokens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLEANER_HOME", str(tmp_path / "gc"))
    path = token_path_for("personal")
    assert path.name == "personal.json"
    assert path.parent.name == "tokens"


def test_write_secret_file(tmp_path: Path) -> None:
    target = tmp_path / "secret.json"
    write_secret_file(target, '{"token":"x"}')
    assert target.read_text(encoding="utf-8") == '{"token":"x"}'
