"""Mailbox scans: storage X-ray or subscriptions/marketing map."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from gmail_cleaner.accounts.registry import Account
from gmail_cleaner.auth.oauth import get_gmail_service, verify_account_email
from gmail_cleaner.gmail.client import GmailClient, MessageMeta
from gmail_cleaner.history.db import HistoryStore
from gmail_cleaner.policy.models import (
    LOCATION_LABELS,
    ScanLocation,
    ScanMode,
    build_scan_queries,
    load_policy,
)

SortBy = Literal["size", "count"]


@dataclass
class SenderBucket:
    sender: str
    message_count: int
    est_bytes: int
    sample_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryBucket:
    name: str
    query: str
    message_count: int
    est_bytes: int
    sample_ids: list[str] = field(default_factory=list)
    failed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    run_id: str
    account_id: str
    email: str
    queries: list[QueryBucket]
    senders: list[SenderBucket]
    total_messages: int
    total_est_bytes: int
    failed_metadata: int = 0
    mode: ScanMode = "storage"
    location: ScanLocation = "all"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "account_id": self.account_id,
            "email": self.email,
            "mode": self.mode,
            "location": self.location,
            "location_label": LOCATION_LABELS[self.location],
            "queries": [q.to_dict() for q in self.queries],
            "senders": [s.to_dict() for s in self.senders],
            "total_messages": self.total_messages,
            "total_est_bytes": self.total_est_bytes,
            "failed_metadata": self.failed_metadata,
        }

    def summary_dict(self) -> dict[str, Any]:
        """Compact summary for SQLite (no huge id lists)."""
        return {
            "run_id": self.run_id,
            "account_id": self.account_id,
            "email": self.email,
            "mode": self.mode,
            "location": self.location,
            "location_label": LOCATION_LABELS[self.location],
            "total_messages": self.total_messages,
            "total_est_bytes": self.total_est_bytes,
            "failed_metadata": self.failed_metadata,
            "queries": [
                {
                    "name": q.name,
                    "query": q.query,
                    "message_count": q.message_count,
                    "est_bytes": q.est_bytes,
                    "failed_count": q.failed_count,
                }
                for q in self.queries
            ],
            "top_senders": [
                {
                    "sender": s.sender,
                    "message_count": s.message_count,
                    "est_bytes": s.est_bytes,
                }
                for s in self.senders[:40]
            ],
        }


def _aggregate_senders(
    messages: list[MessageMeta],
    *,
    ignore_senders: list[str],
    sample_limit: int = 20,
    sort_by: SortBy = "size",
) -> list[SenderBucket]:
    ignore = {s.lower() for s in ignore_senders}
    counts: dict[str, int] = defaultdict(int)
    sizes: dict[str, int] = defaultdict(int)
    samples: dict[str, list[str]] = defaultdict(list)

    for msg in messages:
        sender = msg.sender or "unknown"
        if sender in ignore:
            continue
        counts[sender] += 1
        sizes[sender] += msg.size_estimate
        if len(samples[sender]) < sample_limit:
            samples[sender].append(msg.id)

    buckets = [
        SenderBucket(
            sender=sender,
            message_count=counts[sender],
            est_bytes=sizes[sender],
            sample_ids=samples[sender],
        )
        for sender in counts
    ]
    if sort_by == "count":
        buckets.sort(key=lambda b: (b.message_count, b.est_bytes), reverse=True)
    else:
        buckets.sort(key=lambda b: (b.est_bytes, b.message_count), reverse=True)
    return buckets


def run_scan(
    account: Account,
    *,
    mode: ScanMode = "storage",
    location: ScanLocation = "all",
    history: HistoryStore | None = None,
    max_messages_per_query: int | None = None,
    on_progress: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> ScanResult:
    history = history or HistoryStore()
    run_id = run_id or history.start_run(account.id, f"scan:{mode}:{location}")
    custom = load_policy()
    queries = build_scan_queries(mode, location, custom_policy=custom)
    sort_by: SortBy = "count" if mode == "subscriptions" else "size"

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        history.log_event(msg, run_id=run_id)

    try:
        service = get_gmail_service(account)
        client = GmailClient(service)
        email = verify_account_email(account, service)
        progress(f"Authenticated as {email}")
        progress(f"Mode={mode} · Location={location} ({LOCATION_LABELS[location]})")

        all_metas: dict[str, MessageMeta] = {}
        query_buckets: list[QueryBucket] = []
        total_failed = 0

        for pq in queries:
            progress(f"Listing: {pq.name} ({pq.q})")
            ids = client.list_message_ids(pq.q, max_results=max_messages_per_query)
            progress(f"Found {len(ids)} message ids for {pq.name}")

            missing = [mid for mid in ids if mid not in all_metas]
            query_failed = 0
            if missing:
                progress(f"Fetching metadata for {len(missing)} messages ({pq.name})")

                def _meta_progress(done: int, total: int, name: str = pq.name) -> None:
                    if done == total or done % 200 == 0:
                        progress(f"Metadata {name}: {done}/{total}")

                batch = client.get_metadata_batch(missing, on_progress=_meta_progress)
                for meta in batch.messages:
                    all_metas[meta.id] = meta
                query_failed = len(batch.failed_ids)
                total_failed += query_failed
                if query_failed:
                    progress(
                        f"WARNING: {query_failed} metadata fetches failed for {pq.name}"
                    )
                    for err in batch.errors[:3]:
                        short = err if len(err) < 160 else err[:157] + "..."
                        progress(f"  {short}")

            matched = [all_metas[mid] for mid in ids if mid in all_metas]
            est = sum(m.size_estimate for m in matched)
            query_buckets.append(
                QueryBucket(
                    name=pq.name,
                    query=pq.q,
                    message_count=len(matched),
                    est_bytes=est,
                    sample_ids=ids[:20],
                    failed_count=query_failed,
                )
            )
            history.add_finding(
                run_id,
                bucket="query",
                sender=None,
                query=pq.q,
                message_count=len(matched),
                est_bytes=est,
                sample_ids=ids[:20],
            )

        senders = _aggregate_senders(
            list(all_metas.values()),
            ignore_senders=custom.ignore_senders,
            sort_by=sort_by,
        )
        for sender in senders[:150]:
            history.add_finding(
                run_id,
                bucket="sender",
                sender=sender.sender,
                query=None,
                message_count=sender.message_count,
                est_bytes=sender.est_bytes,
                sample_ids=sender.sample_ids,
            )

        result = ScanResult(
            run_id=run_id,
            account_id=account.id,
            email=email,
            queries=query_buckets,
            senders=senders,
            total_messages=len(all_metas),
            total_est_bytes=sum(m.size_estimate for m in all_metas.values()),
            failed_metadata=total_failed,
            mode=mode,
            location=location,
        )
        history.finish_run(run_id, status="completed", summary=result.summary_dict())
        if total_failed:
            progress(f"Scan completed with {total_failed} metadata failures")
        return result
    except Exception as exc:
        history.finish_run(
            run_id,
            status="failed",
            summary={"error": str(exc), "mode": mode, "location": location},
        )
        history.log_event(str(exc), run_id=run_id, level="error")
        raise
