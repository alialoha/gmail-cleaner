"""Multi-account registry stored under ~/.gmail-cleaner/accounts.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from gmail_cleaner.paths import accounts_path, ensure_layout, expand, validate_account_id

ScopeName = Literal["modify", "full"]


class Account(BaseModel):
    id: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    credentials_file: Path
    token_file: Path
    scope: ScopeName = "modify"

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        return validate_account_id(value)

    @field_validator("credentials_file", "token_file", mode="before")
    @classmethod
    def _expand_path(cls, value: str | Path) -> Path:
        return expand(value)


class AccountRegistry:
    def __init__(self, path: Path | None = None) -> None:
        ensure_layout()
        self.path = path or accounts_path()

    def load(self) -> list[Account]:
        if not self.path.exists():
            return []
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        items = raw.get("accounts") or []
        return [Account.model_validate(item) for item in items]

    def save(self, accounts: list[Account]) -> None:
        payload = {
            "accounts": [
                {
                    "id": a.id,
                    "email": a.email,
                    "credentials_file": str(a.credentials_file),
                    "token_file": str(a.token_file),
                    "scope": a.scope,
                }
                for a in accounts
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

    def get(self, account_id: str) -> Account:
        for account in self.load():
            if account.id == account_id:
                return account
        raise KeyError(f"Unknown account id: {account_id}")

    def add(self, account: Account, *, replace: bool = False) -> None:
        accounts = self.load()
        existing = {a.id: i for i, a in enumerate(accounts)}
        if account.id in existing:
            if not replace:
                raise ValueError(f"Account id already exists: {account.id}")
            accounts[existing[account.id]] = account
        else:
            accounts.append(account)
        self.save(accounts)

    def remove(self, account_id: str) -> Account:
        accounts = self.load()
        kept: list[Account] = []
        removed: Account | None = None
        for account in accounts:
            if account.id == account_id:
                removed = account
            else:
                kept.append(account)
        if removed is None:
            raise KeyError(f"Unknown account id: {account_id}")
        self.save(kept)
        return removed
