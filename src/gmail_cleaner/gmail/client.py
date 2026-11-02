"""Thin Gmail API wrapper with pagination and batch helpers."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Any

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import BatchHttpRequest


@dataclass
class MessageMeta:
    id: str
    thread_id: str
    sender: str
    subject: str
    size_estimate: int
    label_ids: list[str]
    internal_date: str | None = None


@dataclass
class MetadataBatchResult:
    messages: list[MessageMeta] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _header_map(payload_headers: list[dict[str, str]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in payload_headers or []:
        name = item.get("name")
        value = item.get("value")
        if name and value:
            out[name.lower()] = value
    return out


def _is_rate_limited(exc: BaseException) -> bool:
    if not isinstance(exc, HttpError):
        return False
    status = getattr(exc.resp, "status", None)
    if status == 429:
        return True
    if status != 403:
        return False
    reason = ""
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        errors = (payload.get("error") or {}).get("errors") or []
        if errors:
            reason = str(errors[0].get("reason") or "")
        if not reason:
            reason = str((payload.get("error") or {}).get("status") or "")
    except Exception:
        reason = str(exc)
    return reason in {"rateLimitExceeded", "userRateLimitExceeded", "RESOURCE_EXHAUSTED"}


def _meta_from_response(response: dict[str, Any]) -> MessageMeta:
    headers = _header_map((response.get("payload") or {}).get("headers"))
    raw_from = headers.get("from", "")
    _, email_addr = parseaddr(raw_from)
    return MessageMeta(
        id=response["id"],
        thread_id=response.get("threadId", ""),
        sender=(email_addr or raw_from or "unknown").lower(),
        subject=headers.get("subject", ""),
        size_estimate=int(response.get("sizeEstimate") or 0),
        label_ids=list(response.get("labelIds") or []),
        internal_date=response.get("internalDate"),
    )


class GmailClient:
    def __init__(self, service: Resource, *, max_retries: int = 8) -> None:
        self.service = service
        self.max_retries = max_retries

    def _execute(self, request: Any) -> Any:
        delay = 2.0
        for attempt in range(self.max_retries):
            try:
                return request.execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                retryable = status in {429, 500, 503} or _is_rate_limited(exc)
                if retryable and attempt < self.max_retries - 1:
                    # Rate limits often need a longer cool-down than 5xx.
                    sleep_for = delay * (3 if _is_rate_limited(exc) else 1)
                    time.sleep(min(sleep_for, 90))
                    delay = min(delay * 2, 60)
                    continue
                raise

    def list_message_ids(
        self,
        query: str,
        *,
        max_results: int | None = None,
        page_size: int = 500,
    ) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "q": query,
                "maxResults": min(page_size, 500),
                "includeSpamTrash": True,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            data = self._execute(self.service.users().messages().list(**kwargs))
            for item in data.get("messages") or []:
                ids.append(item["id"])
                if max_results is not None and len(ids) >= max_results:
                    return ids
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            # Pace list pagination to reduce unit-cost spikes.
            time.sleep(0.25)
        return ids

    def get_metadata_batch(
        self,
        message_ids: list[str],
        *,
        batch_size: int = 10,
        inter_batch_sleep: float = 1.25,
        max_rounds: int = 6,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> MetadataBatchResult:
        """
        Fetch metadata in small batches.

        Gmail charges ~5 units per messages.get. Large parallel batches trip
        'Units per minute per user' quickly; we pace requests and retry
        rate-limited ids.
        """
        result = MetadataBatchResult()
        pending = list(dict.fromkeys(message_ids))
        total = len(pending)
        done = 0

        for round_idx in range(max_rounds):
            if not pending:
                break
            next_pending: list[str] = []
            rate_limited_this_round = 0

            for start in range(0, len(pending), batch_size):
                chunk = pending[start : start + batch_size]
                chunk_errors: dict[str, Exception] = {}

                def _callback(
                    request_id: str,
                    response: dict[str, Any],
                    exception: Exception | None,
                    _chunk_errors: dict[str, Exception] = chunk_errors,
                ) -> None:
                    if exception is not None:
                        _chunk_errors[request_id] = exception
                        return
                    result.messages.append(_meta_from_response(response))

                batch: BatchHttpRequest = self.service.new_batch_http_request(
                    callback=_callback
                )
                for mid in chunk:
                    req = (
                        self.service.users()
                        .messages()
                        .get(
                            userId="me",
                            id=mid,
                            format="metadata",
                            metadataHeaders=["From", "Subject"],
                        )
                    )
                    batch.add(req, request_id=mid)

                try:
                    self._execute(batch)
                except HttpError as exc:
                    if _is_rate_limited(exc):
                        rate_limited_this_round += len(chunk)
                        next_pending.extend(chunk)
                        time.sleep(45)
                        continue
                    raise

                for mid in chunk:
                    if mid not in chunk_errors:
                        done += 1
                        continue
                    exc = chunk_errors[mid]
                    if _is_rate_limited(exc):
                        rate_limited_this_round += 1
                        next_pending.append(mid)
                    else:
                        result.failed_ids.append(mid)
                        result.errors.append(f"{mid}: {exc}")

                if on_progress:
                    on_progress(min(done + len(next_pending), total), total)
                time.sleep(inter_batch_sleep)

            pending = list(dict.fromkeys(next_pending))
            if pending and round_idx < max_rounds - 1:
                # Cool down before retrying rate-limited leftovers.
                time.sleep(20 + round_idx * 10)

        for mid in pending:
            result.failed_ids.append(mid)
            result.errors.append(f"{mid}: still rate-limited after retries")

        return result

    def trash_messages(self, message_ids: list[str], *, chunk_size: int = 1000) -> int:
        """Move messages to Trash via batchModify."""
        moved = 0
        for start in range(0, len(message_ids), chunk_size):
            chunk = message_ids[start : start + chunk_size]
            body = {
                "ids": chunk,
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX", "UNREAD"],
            }
            self._execute(
                self.service.users().messages().batchModify(userId="me", body=body)
            )
            moved += len(chunk)
            time.sleep(0.25)
        return moved

    def permanently_delete(self, message_ids: list[str], *, chunk_size: int = 1000) -> int:
        """Permanent delete. Requires full mail scope."""
        deleted = 0
        for start in range(0, len(message_ids), chunk_size):
            chunk = message_ids[start : start + chunk_size]
            body = {"ids": chunk}
            self._execute(
                self.service.users().messages().batchDelete(userId="me", body=body)
            )
            deleted += len(chunk)
            time.sleep(0.25)
        return deleted

    def empty_trash(self) -> int:
        ids = self.list_message_ids("in:trash")
        if not ids:
            return 0
        return self.permanently_delete(ids)

    def trash_count(self) -> int:
        return len(self.list_message_ids("in:trash"))

    def profile_email(self) -> str:
        profile = self._execute(self.service.users().getProfile(userId="me"))
        return str(profile.get("emailAddress", ""))
