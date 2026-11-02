"""FastAPI surface shared by CLI `serve` and the React SPA."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gmail_cleaner import __version__ as APP_VERSION
from gmail_cleaner.accounts.registry import AccountRegistry
from gmail_cleaner.actions.cleanup import apply_cleanup, empty_account_trash
from gmail_cleaner.auth.oauth import get_gmail_service
from gmail_cleaner.gmail.client import GmailClient
from gmail_cleaner.history.db import HistoryStore
from gmail_cleaner.paths import ensure_layout
from gmail_cleaner.report.builder import save_report
from gmail_cleaner.scan.scanner import run_scan


class ScanRequest(BaseModel):
    account_id: str
    max_per_query: int | None = None
    background: bool = True


class PreviewRequest(BaseModel):
    account_id: str
    sender: str | None = None
    query: str | None = None


class CleanupRequest(BaseModel):
    account_id: str
    message_ids: list[str] = Field(default_factory=list)
    sender: str | None = None
    query: str | None = None
    confirm: bool = False
    permanent: bool = False
    i_understand_permanent: bool = False


class EmptyTrashRequest(BaseModel):
    account_id: str
    confirm: bool = False


def _resolve_message_ids(
    account_id: str,
    *,
    message_ids: list[str],
    sender: str | None,
    query: str | None,
) -> list[str]:
    ids = list(message_ids)
    q = query
    if sender and not q:
        q = f"from:{sender}"
    if q:
        account = AccountRegistry().get(account_id)
        client = GmailClient(get_gmail_service(account))
        ids.extend(client.list_message_ids(q))
    return list(dict.fromkeys(ids))


def create_app() -> FastAPI:
    ensure_layout()
    app = FastAPI(title="Gmail Cleaner API", version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8787",
            "http://localhost:8787",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/api/accounts")
    def list_accounts() -> list[dict[str, Any]]:
        return [
            {
                "id": a.id,
                "email": a.email,
                "scope": a.scope,
                "has_token": a.token_file.exists(),
            }
            for a in AccountRegistry().load()
        ]

    @app.get("/api/accounts/{account_id}/trash-count")
    def trash_count(account_id: str) -> dict[str, Any]:
        try:
            account = AccountRegistry().get(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        client = GmailClient(get_gmail_service(account))
        count = client.trash_count()
        return {"account_id": account_id, "count": count}

    @app.get("/api/runs")
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        return HistoryStore().list_runs(limit=limit)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = HistoryStore().get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.post("/api/scan")
    def scan(body: ScanRequest) -> dict[str, Any]:
        try:
            account = AccountRegistry().get(body.account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not body.background:
            result = run_scan(account, max_messages_per_query=body.max_per_query)
            path = save_report(result)
            payload = result.to_dict()
            payload["report_path"] = str(path)
            return payload

        history = HistoryStore()
        run_id = history.start_run(account.id, "scan")

        def _worker() -> None:
            try:
                result = run_scan(
                    account,
                    history=history,
                    max_messages_per_query=body.max_per_query,
                    run_id=run_id,
                )
                save_report(result)
            except Exception as exc:  # noqa: BLE001 - persist failure into history
                current = history.get_run(run_id)
                if current and current.get("status") == "running":
                    history.finish_run(
                        run_id, status="failed", summary={"error": str(exc)}
                    )
                history.log_event(str(exc), run_id=run_id, level="error")

        threading.Thread(target=_worker, daemon=True).start()
        return {"run_id": run_id, "status": "running", "account_id": account.id}

    @app.post("/api/preview")
    def preview(body: PreviewRequest) -> dict[str, Any]:
        if not body.sender and not body.query:
            raise HTTPException(status_code=400, detail="Provide sender and/or query")
        try:
            AccountRegistry().get(body.account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ids = _resolve_message_ids(
            body.account_id,
            message_ids=[],
            sender=body.sender,
            query=body.query,
        )
        return {
            "account_id": body.account_id,
            "sender": body.sender,
            "query": body.query or (f"from:{body.sender}" if body.sender else None),
            "message_count": len(ids),
            "message_ids": ids[:50],
            "all_message_ids": ids,
        }

    @app.post("/api/cleanup")
    def cleanup(body: CleanupRequest) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(
                status_code=400,
                detail="confirm must be true to modify the mailbox",
            )
        if body.permanent and not body.i_understand_permanent:
            raise HTTPException(
                status_code=400,
                detail="permanent delete also requires i_understand_permanent=true",
            )
        try:
            account = AccountRegistry().get(body.account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            ids = _resolve_message_ids(
                body.account_id,
                message_ids=body.message_ids,
                sender=body.sender,
                query=body.query,
            )
            result = apply_cleanup(
                account,
                ids,
                confirm=True,
                permanent=body.permanent,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "run_id": result.run_id,
            "action": result.action,
            "message_count": result.message_count,
            "permanent": result.permanent,
        }

    @app.post("/api/empty-trash")
    def empty_trash(body: EmptyTrashRequest) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm must be true")
        try:
            account = AccountRegistry().get(body.account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            result = empty_account_trash(account, confirm=True)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {
            "run_id": result.run_id,
            "action": result.action,
            "message_count": result.message_count,
            "permanent": result.permanent,
        }

    return app
