"""FastAPI surface shared by CLI `serve` and the future React SPA."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gmail_cleaner import __version__ as APP_VERSION
from gmail_cleaner.accounts.registry import AccountRegistry
from gmail_cleaner.actions.cleanup import apply_cleanup, empty_account_trash
from gmail_cleaner.history.db import HistoryStore
from gmail_cleaner.paths import ensure_layout
from gmail_cleaner.report.builder import save_report
from gmail_cleaner.scan.scanner import run_scan


class ScanRequest(BaseModel):
    account_id: str
    max_per_query: int | None = None


class CleanupRequest(BaseModel):
    account_id: str
    message_ids: list[str] = Field(default_factory=list)
    confirm: bool = False
    permanent: bool = False
    i_understand_permanent: bool = False


class EmptyTrashRequest(BaseModel):
    account_id: str
    confirm: bool = False


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
        result = run_scan(account, max_messages_per_query=body.max_per_query)
        path = save_report(result)
        payload = result.to_dict()
        payload["report_path"] = str(path)
        return payload

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
            result = apply_cleanup(
                account,
                body.message_ids,
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
