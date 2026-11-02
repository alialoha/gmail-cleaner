"""Report helpers for terminal + JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from gmail_cleaner.paths import reports_dir
from gmail_cleaner.scan.scanner import ScanResult


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num} B"


def save_report(result: ScanResult, path: Path | None = None) -> Path:
    out = path or (reports_dir() / f"{result.run_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return out


def render_scan_table(result: ScanResult, console: Console | None = None, top_n: int = 20) -> None:
    console = console or Console()
    from gmail_cleaner.policy.models import LOCATION_LABELS

    console.print(
        f"[bold]Scan {result.run_id}[/bold] · {result.email} · "
        f"mode={result.mode} · {LOCATION_LABELS.get(result.location, result.location)} · "
        f"{result.total_messages} msgs · ~{format_bytes(result.total_est_bytes)}"
    )
    if result.failed_metadata:
        console.print(
            f"[yellow]Warning:[/yellow] {result.failed_metadata} metadata fetches failed; "
            "sizes may be undercounted."
        )

    qtable = Table(title="Query buckets")
    qtable.add_column("Name")
    qtable.add_column("Query")
    qtable.add_column("Messages", justify="right")
    qtable.add_column("Est. size", justify="right")
    qtable.add_column("Failed", justify="right")
    for q in result.queries:
        qtable.add_row(
            q.name,
            q.query,
            str(q.message_count),
            format_bytes(q.est_bytes),
            str(q.failed_count),
        )
    console.print(qtable)

    rank = "message count" if result.mode == "subscriptions" else "estimated size"
    stable = Table(title=f"Top {top_n} senders by {rank}")
    stable.add_column("Sender")
    stable.add_column("Messages", justify="right")
    stable.add_column("Est. size", justify="right")
    for sender in result.senders[:top_n]:
        stable.add_row(sender.sender, str(sender.message_count), format_bytes(sender.est_bytes))
    console.print(stable)
