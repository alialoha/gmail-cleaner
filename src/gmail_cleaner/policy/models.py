"""Scan policy / modes / mailbox locations (Gmail tabs)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from gmail_cleaner.paths import policy_path

ScanMode = Literal["storage", "subscriptions"]
ScanLocation = Literal[
    "all",
    "inbox",
    "primary",
    "promotions",
    "social",
    "updates",
    "forums",
]

MODES: tuple[ScanMode, ...] = ("storage", "subscriptions")
LOCATIONS: tuple[ScanLocation, ...] = (
    "all",
    "inbox",
    "primary",
    "promotions",
    "social",
    "updates",
    "forums",
)

LOCATION_LABELS: dict[ScanLocation, str] = {
    "all": "Entire mailbox (all mail)",
    "inbox": "All Inbox tabs",
    "primary": "Primary tab",
    "promotions": "Promotions tab",
    "social": "Social tab",
    "updates": "Updates tab",
    "forums": "Forums tab",
}

# Gmail search fragment for each location
LOCATION_QUERY: dict[ScanLocation, str] = {
    "all": "",
    "inbox": "in:inbox",
    "primary": "category:primary",
    "promotions": "category:promotions",
    "social": "category:social",
    "updates": "category:updates",
    "forums": "category:forums",
}

# Legacy default file format still works as a custom storage query list.
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


def _and_location(query: str, location: ScanLocation) -> str:
    fragment = LOCATION_QUERY[location]
    if not fragment:
        return query
    if not query:
        return fragment
    return f"({query}) {fragment}"


def build_scan_queries(
    mode: ScanMode = "storage",
    location: ScanLocation = "all",
    *,
    custom_policy: Policy | None = None,
) -> list[PolicyQuery]:
    """
    Build Gmail queries for a scan profile.

    - storage: find what eats quota (large mail, optional spam/trash)
    - subscriptions: newsletters / ads / marketing-style tabs and senders
    - location: entire mailbox, all inbox tabs, or one Gmail category tab
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    if location not in LOCATIONS:
        raise ValueError(f"Unknown location: {location}")

    if mode == "subscriptions":
        return _subscription_queries(location)

    # storage
    if custom_policy is not None and location == "all":
        # Preserve optional ~/.gmail-cleaner/policy.yaml for classic full-mailbox storage scans.
        return custom_policy.enabled_queries()
    return _storage_queries(location)


def _storage_queries(location: ScanLocation) -> list[PolicyQuery]:
    core = [
        ("large_attachments", "has:attachment larger:5M"),
        ("huge_messages", "larger:10M"),
    ]
    out = [
        PolicyQuery(name=name, q=_and_location(q, location))
        for name, q in core
    ]

    # Category age buckets only when scanning broadly (avoid duplicating a single-tab filter).
    if location in {"all", "inbox"}:
        extras = [
            ("old_promotions", "category:promotions older_than:1y"),
            ("old_social", "category:social older_than:6m"),
            ("old_updates", "category:updates older_than:1y"),
        ]
        out.extend(
            PolicyQuery(name=name, q=_and_location(q, location))
            for name, q in extras
        )

    if location == "all":
        out.extend(
            [
                PolicyQuery(name="spam", q="in:spam"),
                PolicyQuery(name="trash", q="in:trash"),
            ]
        )
    return out


def _subscription_queries(location: ScanLocation) -> list[PolicyQuery]:
    if location in {"promotions", "social", "updates", "forums", "primary"}:
        base = LOCATION_QUERY[location]
        return [
            PolicyQuery(name=f"{location}_all", q=base),
            PolicyQuery(name=f"{location}_older_6m", q=f"{base} older_than:6m"),
            PolicyQuery(name=f"{location}_older_1y", q=f"{base} older_than:1y"),
            PolicyQuery(
                name=f"{location}_unsubscribe",
                q=_and_location("unsubscribe", location),
            ),
        ]

    # inbox or entire mailbox: break out marketing-style tabs
    prefix = "in:inbox " if location == "inbox" else ""
    return [
        PolicyQuery(name="promotions", q=f"{prefix}category:promotions".strip()),
        PolicyQuery(name="updates", q=f"{prefix}category:updates".strip()),
        PolicyQuery(name="social", q=f"{prefix}category:social".strip()),
        PolicyQuery(name="forums", q=f"{prefix}category:forums".strip()),
        PolicyQuery(
            name="unsubscribe_mentions",
            q=f"{prefix}unsubscribe".strip(),
        ),
        PolicyQuery(
            name="promotions_older_1y",
            q=f"{prefix}category:promotions older_than:1y".strip(),
        ),
    ]


def location_filter_query(location: ScanLocation) -> str:
    """Fragment to AND onto from:sender previews so deletes stay in-tab when possible."""
    return LOCATION_QUERY[location]
