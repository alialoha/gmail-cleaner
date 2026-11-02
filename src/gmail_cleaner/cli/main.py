"""gmail-cleaner CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from gmail_cleaner import __version__
from gmail_cleaner.accounts.registry import Account, AccountRegistry
from gmail_cleaner.actions.cleanup import apply_cleanup, empty_account_trash
from gmail_cleaner.auth.oauth import get_gmail_service, verify_account_email
from gmail_cleaner.gmail.client import GmailClient
from gmail_cleaner.history.db import HistoryStore
from gmail_cleaner.paths import credentials_dir, ensure_layout, token_path_for, validate_account_id
from gmail_cleaner.report.builder import format_bytes, render_scan_table, save_report
from gmail_cleaner.scan.scanner import run_scan

app = typer.Typer(
    name="gmail-cleaner",
    help="Multi-account Gmail storage cleaner (scan -> report -> confirm -> trash).",
    no_args_is_help=True,
    invoke_without_command=True,
)
accounts_app = typer.Typer(help="Manage Gmail accounts.")
app.add_typer(accounts_app, name="accounts")

console = Console()

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _registry() -> AccountRegistry:
    ensure_layout()
    return AccountRegistry()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None and not version:
        console.print(ctx.get_help())
        raise typer.Exit()


@accounts_app.command("list")
def accounts_list() -> None:
    """List configured accounts."""
    rows = _registry().load()
    if not rows:
        console.print(
            "No accounts yet. Run: [bold]gmail-cleaner accounts add[/bold]\n"
            f"Secrets live under [cyan]{ensure_layout()}[/cyan]"
        )
        return
    table = Table(title="Accounts")
    table.add_column("ID")
    table.add_column("Email")
    table.add_column("Scope")
    table.add_column("Token")
    for account in rows:
        table.add_row(
            account.id,
            account.email,
            account.scope,
            "yes" if account.token_file.exists() else "missing",
        )
    console.print(table)


@accounts_app.command("add")
def accounts_add(
    account_id: str = typer.Option(..., "--id", help="Short id, e.g. personal"),
    email: str = typer.Option(..., "--email"),
    credentials: Path = typer.Option(
        ...,
        "--credentials",
        exists=True,
        dir_okay=False,
        help="Path to Google OAuth Desktop client JSON",
    ),
    scope: str = typer.Option(
        "modify",
        "--scope",
        help="modify = trash; full = permanent delete / empty trash (needed to free quota)",
    ),
    login: bool = typer.Option(True, "--login/--no-login", help="Run browser OAuth now"),
) -> None:
    """Register an account. Credentials/tokens stay under ~/.gmail-cleaner/."""
    if scope not in {"modify", "full"}:
        raise typer.BadParameter("scope must be 'modify' or 'full'")
    try:
        validate_account_id(account_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    ensure_layout()
    token_file = token_path_for(account_id)
    account = Account(
        id=account_id,
        email=email,
        credentials_file=credentials,
        token_file=token_file,
        scope=scope,  # type: ignore[arg-type]
    )
    _registry().add(account, replace=True)
    console.print(f"Saved account [bold]{account_id}[/bold] -> {_registry().path}")
    console.print(f"Tip: keep client JSON under [cyan]{credentials_dir()}[/cyan]")
    if scope == "modify":
        console.print(
            "[yellow]Note:[/yellow] Trash still counts toward Google storage. "
            "Use [bold]--scope full[/bold] when you need empty-trash / permanent delete "
            "to reclaim quota immediately."
        )

    if login:
        service = get_gmail_service(account)
        actual = verify_account_email(account, service)
        console.print(f"[green]OAuth complete.[/green] Authenticated as {actual}")
        console.print(f"Token stored at {token_file}")


@accounts_app.command("remove")
def accounts_remove(
    account_id: str = typer.Argument(...),
    delete_token: bool = typer.Option(False, "--delete-token"),
) -> None:
    """Remove an account from the registry."""
    removed = _registry().remove(account_id)
    if delete_token and removed.token_file.exists():
        removed.token_file.unlink()
        console.print(f"Deleted token {removed.token_file}")
    console.print(f"Removed account {account_id}")


@accounts_app.command("auth")
def accounts_auth(
    account_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Force re-consent"),
) -> None:
    """Refresh or create OAuth token for an account."""
    account = _registry().get(account_id)
    service = get_gmail_service(account, force_consent=force)
    actual = verify_account_email(account, service)
    console.print(f"[green]Authenticated[/green] {actual}")


@app.command("scan")
def scan_cmd(
    account: str | None = typer.Option(None, "--account", "-a", help="Account id"),
    all_accounts: bool = typer.Option(False, "--all", help="Scan every account"),
    max_per_query: int | None = typer.Option(
        None,
        "--max-per-query",
        help="Optional cap per query (useful for smoke tests)",
    ),
    top: int = typer.Option(20, "--top", help="Top senders to show"),
) -> None:
    """Dry-run storage scan. Never deletes."""
    reg = _registry()
    targets: list[Account]
    if all_accounts:
        targets = reg.load()
    elif account:
        targets = [reg.get(account)]
    else:
        raise typer.BadParameter("Pass --account ID or --all")

    if not targets:
        raise typer.Exit("No accounts configured.")

    history = HistoryStore()
    for target in targets:
        console.rule(f"Scanning {target.id}")
        result = run_scan(
            target,
            history=history,
            max_messages_per_query=max_per_query,
            on_progress=lambda msg: console.log(msg),
        )
        path = save_report(result)
        render_scan_table(result, console=console, top_n=top)
        console.print(f"Report saved: [cyan]{path}[/cyan]")
        console.print(
            "Next: review senders, then "
            f"[bold]gmail-cleaner trash --account {target.id} --from-run {result.run_id} "
            "--sender ADDRESS --confirm[/bold]"
        )


@app.command("trash")
def trash_cmd(
    account: str = typer.Option(..., "--account", "-a"),
    sender: str | None = typer.Option(None, "--sender", help="Delete mail from this sender"),
    query: str | None = typer.Option(None, "--query", help="Gmail search query"),
    from_run: str | None = typer.Option(None, "--from-run", help="Use sender samples from a scan"),
    ids_file: Path | None = typer.Option(
        None,
        "--ids-file",
        exists=True,
        dir_okay=False,
        help="Text file with one message id per line",
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Required to actually trash"),
    permanent: bool = typer.Option(
        False,
        "--permanent",
        help="Permanently delete (second-level danger; needs scope=full)",
    ),
    i_understand: bool = typer.Option(
        False,
        "--i-understand-permanent",
        help="Required together with --permanent --confirm",
    ),
    dry_run_list: bool = typer.Option(
        True,
        "--list/--no-list",
        help="List matching ids before acting",
    ),
) -> None:
    """Move matching messages to Trash (or permanently delete with --permanent --confirm)."""
    if not any([sender, query, ids_file]):
        raise typer.BadParameter("Provide --sender, --query, and/or --ids-file")

    acct = _registry().get(account)
    history = HistoryStore()
    message_ids: list[str] = []

    if ids_file:
        raw_lines = ids_file.read_text(encoding="utf-8").splitlines()
        message_ids.extend(line.strip() for line in raw_lines if line.strip())

    if from_run:
        run = history.get_run(from_run)
        if not run:
            raise typer.BadParameter(f"Unknown run id: {from_run}")
        if run.get("account_id") != account:
            raise typer.BadParameter(
                f"Run {from_run} belongs to account '{run.get('account_id')}', "
                f"not '{account}'. Refuse to cross-apply deletes."
            )
        if sender:
            for finding in run["findings"]:
                if finding.get("bucket") == "sender" and finding.get("sender") == sender.lower():
                    samples = json.loads(finding.get("sample_ids_json") or "[]")
                    message_ids.extend(samples)
                    query = query or f"from:{sender}"

    if sender and not query:
        query = f"from:{sender}"

    if query:
        client = GmailClient(get_gmail_service(acct))
        console.log(f"Listing ids for query: {query}")
        message_ids.extend(client.list_message_ids(query))

    unique_ids = list(dict.fromkeys(message_ids))
    console.print(f"Matched [bold]{len(unique_ids)}[/bold] messages")
    if dry_run_list and unique_ids:
        for mid in unique_ids[:30]:
            console.print(f"  {mid}")
        if len(unique_ids) > 30:
            console.print(f"  ... and {len(unique_ids) - 30} more")

    if not confirm:
        console.print(
            "[yellow]Dry-run only.[/yellow] Re-run with [bold]--confirm[/bold] to "
            + ("permanently delete." if permanent else "move to Trash.")
        )
        raise typer.Exit(0)

    if permanent:
        if not i_understand:
            raise typer.BadParameter(
                "Permanent delete also requires --i-understand-permanent"
            )
        console.print(
            "[red bold]WARNING:[/red bold] permanent delete cannot be undone."
        )

    result = apply_cleanup(
        acct,
        unique_ids,
        confirm=True,
        permanent=permanent,
        history=history,
        on_progress=lambda msg: console.log(msg),
    )
    console.print(
        f"[green]OK[/green] run={result.run_id} action={result.action} count={result.message_count}"
    )


@app.command("empty-trash")
def empty_trash_cmd(
    account: str = typer.Option(..., "--account", "-a"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Permanently delete everything in Trash (requires scope=full)."""
    acct = _registry().get(account)
    client = GmailClient(get_gmail_service(acct))
    count = client.trash_count()
    console.print(f"Trash currently has [bold]{count}[/bold] messages")
    if not confirm:
        console.print(
            "[yellow]Dry-run.[/yellow] Pass --confirm to permanently delete them "
            "(requires scope=full)."
        )
        raise typer.Exit(0)
    result = empty_account_trash(
        acct,
        confirm=True,
        on_progress=lambda msg: console.log(msg),
    )
    console.print(f"[green]OK[/green] permanently removed {result.message_count} messages")


@app.command("history")
def history_cmd(
    limit: int = typer.Option(20, "--limit"),
    run_id: str | None = typer.Option(None, "--run"),
) -> None:
    """Show scan/action history."""
    store = HistoryStore()
    if run_id:
        run = store.get_run(run_id)
        if not run:
            raise typer.Exit(f"Unknown run: {run_id}")
        console.print_json(json.dumps({k: run[k] for k in run if k != "events"}))
        return

    table = Table(title="Recent runs")
    table.add_column("Run")
    table.add_column("Account")
    table.add_column("Mode")
    table.add_column("Status")
    table.add_column("Started")
    for row in store.list_runs(limit=limit):
        table.add_row(
            row["run_id"],
            row["account_id"],
            row["mode"],
            row["status"],
            row["started_at"],
        )
    console.print(table)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Allow binding outside loopback (dangerous; no API auth yet)",
    ),
) -> None:
    """Start local API (Phase 2 dashboard will use this). Loopback only by default."""
    import uvicorn

    from gmail_cleaner.api.app import create_app

    if host not in _LOOPBACK_HOSTS and not allow_remote:
        raise typer.BadParameter(
            f"Refusing to bind {host!r}. Use 127.0.0.1/localhost, "
            "or pass --allow-remote if you understand there is no API auth yet."
        )
    if host not in _LOOPBACK_HOSTS:
        console.print(
            "[red bold]WARNING:[/red bold] API has no authentication. "
            "Anyone who can reach this host can scan/delete mail."
        )

    console.print(f"API on http://{host}:{port}  (localhost only recommended)")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@app.command("doctor")
def doctor_cmd() -> None:
    """Show local paths and configuration health."""
    home = ensure_layout()
    console.print(f"App home: [cyan]{home}[/cyan]")
    console.print(f"Accounts file: {_registry().path} (exists={_registry().path.exists()})")
    console.print(f"Credentials dir: {credentials_dir()}")
    console.print(f"Tokens dir: {ensure_layout() / 'tokens'}")
    accounts = _registry().load()
    console.print(f"Accounts: {len(accounts)}")
    for account in accounts:
        cred_ok = account.credentials_file.exists()
        tok_ok = account.token_file.exists()
        console.print(
            f"  - {account.id}: creds={'ok' if cred_ok else 'MISSING'} "
            f"token={'ok' if tok_ok else 'missing'} scope={account.scope}"
        )
    console.print(f"Formatter check: {format_bytes(0)}")
