"""Thin Gmail API wrapper with pagination and batch helpers."""

from __future__ import annotations

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


class GmailClient:
    def __init__(self, service: Resource, *, max_retries: int = 5) -> None:
        self.service = service
        self.max_retries = max_retries

    def _execute(self, request: Any) -> Any:
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                return request.execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                # Retry transient failures only. Many 403s are permanent (scope/policy).
                if status in {429, 500, 503} and attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
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
        return ids

    def get_metadata_batch(
        self,
        message_ids: list[str],
        *,
        batch_size: int = 50,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> MetadataBatchResult:
        result = MetadataBatchResult()
        total = len(message_ids)

        def _callback(
            request_id: str,
            response: dict[str, Any],
            exception: Exception | None,
        ) -> None:
            if exception is not None:
                result.failed_ids.append(request_id)
                result.errors.append(f"{request_id}: {exception}")
                return
            headers = _header_map((response.get("payload") or {}).get("headers"))
            raw_from = headers.get("from", "")
            _, email_addr = parseaddr(raw_from)
            result.messages.append(
                MessageMeta(
                    id=response["id"],
                    thread_id=response.get("threadId", ""),
                    sender=(email_addr or raw_from or "unknown").lower(),
                    subject=headers.get("subject", ""),
                    size_estimate=int(response.get("sizeEstimate") or 0),
                    label_ids=list(response.get("labelIds") or []),
                    internal_date=response.get("internalDate"),
                )
            )

        for start in range(0, total, batch_size):
            chunk = message_ids[start : start + batch_size]
            batch: BatchHttpRequest = self.service.new_batch_http_request(callback=_callback)
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
            self._execute(batch)
            if on_progress:
                on_progress(min(start + len(chunk), total), total)
            time.sleep(0.05)

        return result

    def trash_messages(self, message_ids: list[str], *, chunk_size: int = 1000) -> int:
        """Move messages to Trash via batchModify."""
        moved = 0
        for start in range(0, len(message_ids), chunk_size):
            chunk = message_ids[start : start + chunk_size]
            body = {"ids": chunk, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX", "UNREAD"]}
            self._execute(self.service.users().messages().batchModify(userId="me", body=body))
            moved += len(chunk)
            time.sleep(0.1)
        return moved

    def permanently_delete(self, message_ids: list[str], *, chunk_size: int = 1000) -> int:
        """Permanent delete. Requires full mail scope."""
        deleted = 0
        for start in range(0, len(message_ids), chunk_size):
            chunk = message_ids[start : start + chunk_size]
            body = {"ids": chunk}
            self._execute(self.service.users().messages().batchDelete(userId="me", body=body))
            deleted += len(chunk)
            time.sleep(0.1)
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
