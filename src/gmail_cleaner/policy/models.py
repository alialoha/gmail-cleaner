"""Scan policy / default Gmail queries."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from gmail_cleaner.paths import policy_path

DEFAULT_QUERIES = [
    {"name": "large_attachments", "q": "has:attachment larger:5M", "enabled": True},
    {"name": "huge_messages", "q": "larger:10M", "enabled": True},
    {"name": "old_promotions", "q": "category:promotions older_than:1y", "enabled": True},
    {"name": "old_social", "q": "category:social older_than:6m", "enabled": True},
    {"name": "spam", "q": "in:spam", "enabled": True},
    {"name": "trash", "q": "in:trash", "enabled": True},
]


class PolicyQuery(BaseModel):
    name: str
    q: str
    enabled: bool = True


class Policy(BaseModel):
    version: int = 1
    queries: list[PolicyQuery] = Field(
        default_factory=lambda: [PolicyQuery(**q) for q in DEFAULT_QUERIES]
    )
    ignore_senders: list[str] = Field(default_factory=list)

    def enabled_queries(self) -> list[PolicyQuery]:
        return [q for q in self.queries if q.enabled]


def load_policy(path: Path | None = None) -> Policy:
    target = path or policy_path()
    if not target.exists():
        return Policy()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return Policy.model_validate(raw)
