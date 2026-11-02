"""Confirm-gated cleanup actions (trash by default, optional permanent delete)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gmail_cleaner.accounts.registry import Account
from gmail_cleaner.auth.oauth import get_gmail_service
from gmail_cleaner.gmail.client import GmailClient
from gmail_cleaner.history.db import HistoryStore


@dataclass
class CleanupResult:
    run_id: str
    account_id: str
    action: str
    message_count: int
    permanent: bool


def apply_cleanup(
    account: Account,
    message_ids: list[str],
    *,
    confirm: bool,
    permanent: bool = False,
    history: HistoryStore | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CleanupResult:
    if not confirm:
        raise PermissionError(
            "Refusing to modify mailbox without confirm=True / --confirm. "
            "Dry-run only."
        )
    if permanent and account.scope != "full":
        raise PermissionError(
            "Permanent delete requires account scope: full "
            "(https://mail.google.com/). Re-add the account with --scope full and re-auth."
        )

    history = history or HistoryStore()
    mode = "purge" if permanent else "trash"
    run_id = history.start_run(account.id, mode)

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        history.log_event(msg, run_id=run_id)

    unique_ids = list(dict.fromkeys(message_ids))
    try:
        if not unique_ids:
            history.finish_run(run_id, status="completed", summary={"message_count": 0})
            return CleanupResult(run_id, account.id, mode, 0, permanent)

        progress(f"Applying {mode} to {len(unique_ids)} messages")
        client = GmailClient(get_gmail_service(account))
        if permanent:
            count = client.permanently_delete(unique_ids)
        else:
            count = client.trash_messages(unique_ids)

        history.record_action(
            run_id,
            action=mode,
            message_count=count,
            permanent=permanent,
            confirmed=True,
            detail={"requested": len(unique_ids)},
        )
        history.finish_run(
            run_id,
            status="completed",
            summary={"message_count": count, "permanent": permanent},
        )
        progress(f"Done: {count} messages ({mode})")
        return CleanupResult(run_id, account.id, mode, count, permanent)
    except Exception as exc:
        history.finish_run(run_id, status="failed", summary={"error": str(exc)})
        history.log_event(str(exc), run_id=run_id, level="error")
        raise


def empty_account_trash(
    account: Account,
    *,
    confirm: bool,
    history: HistoryStore | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CleanupResult:
    if not confirm:
        raise PermissionError("Refusing to empty trash without confirm=True / --confirm.")
    if account.scope != "full":
        raise PermissionError(
            "Emptying trash permanently requires account scope: full. "
            "Re-add with --scope full and re-auth."
        )

    history = history or HistoryStore()
    run_id = history.start_run(account.id, "empty_trash")

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        history.log_event(msg, run_id=run_id)

    try:
        client = GmailClient(get_gmail_service(account))
        progress("Listing trash...")
        count = client.empty_trash()
        history.record_action(
            run_id,
            action="empty_trash",
            message_count=count,
            permanent=True,
            confirmed=True,
        )
        history.finish_run(run_id, status="completed", summary={"message_count": count})
        progress(f"Permanently deleted {count} trash messages")
        return CleanupResult(run_id, account.id, "empty_trash", count, True)
    except Exception as exc:
        history.finish_run(run_id, status="failed", summary={"error": str(exc)})
        history.log_event(str(exc), run_id=run_id, level="error")
        raise
