"""Filesystem layout for secrets and local data (outside the git repo)."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_ACCOUNT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def app_home() -> Path:
    override = os.environ.get("GMAIL_CLEANER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".gmail-cleaner").resolve()


def ensure_layout(home: Path | None = None) -> Path:
    root = home or app_home()
    for sub in ("credentials", "tokens", "data", "data/reports"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def credentials_dir(home: Path | None = None) -> Path:
    return ensure_layout(home) / "credentials"


def tokens_dir(home: Path | None = None) -> Path:
    return ensure_layout(home) / "tokens"


def data_dir(home: Path | None = None) -> Path:
    return ensure_layout(home) / "data"


def reports_dir(home: Path | None = None) -> Path:
    return data_dir(home) / "reports"


def db_path(home: Path | None = None) -> Path:
    return data_dir(home) / "history.db"


def accounts_path(home: Path | None = None) -> Path:
    return ensure_layout(home) / "accounts.yaml"


def policy_path(home: Path | None = None) -> Path:
    return ensure_layout(home) / "policy.yaml"


def expand(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def validate_account_id(account_id: str) -> str:
    """Reject path traversal and odd ids used in token filenames."""
    if not _ACCOUNT_ID_RE.match(account_id):
        raise ValueError(
            "Account id must be 1-64 chars: letters, digits, _ or - "
            "(no path separators or '..')."
        )
    return account_id


def token_path_for(account_id: str, home: Path | None = None) -> Path:
    safe_id = validate_account_id(account_id)
    path = (tokens_dir(home) / f"{safe_id}.json").resolve()
    root = tokens_dir(home).resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Refusing token path outside tokens dir: {path}")
    return path


def write_secret_file(path: Path, content: str) -> None:
    """Write a secret file with owner-only permissions when the OS supports it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows may ignore or partially apply POSIX modes; best-effort only.
        pass
