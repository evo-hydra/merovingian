"""Typer CLI for Merovingian."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from merovingian.config import MerovingianConfig
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import Consumer, RepoInfo
from merovingian.models.enums import ContractType, FeedbackOutcome, TargetType

app = typer.Typer(
    name="merovingian",
    help="Cross-repository dependency intelligence for AI agents.",
    no_args_is_help=True,
)
console = Console(stderr=True)


def _config() -> MerovingianConfig:
    return MerovingianConfig.load()


@app.command()
def register(
    name: str,
    path: str,
    contract_type: Annotated[
        Optional[str], typer.Option("--type", "-t", help="Contract type: openapi or pydantic")
    ] = None,
) -> None:
    """Register a repository for contract scanning."""
    config = _config()
    ct = ContractType(contract_type) if contract_type else None
    repo = RepoInfo(name=name, path=path, contract_type=ct)

    with MerovingianStore(config.db_path) as store:
        store.register_repo(repo)

    console.print(f"[green]Registered[/green] '{name}' at {path}")


@app.command()
def unregister(name: str) -> None:
    """Unregister a repository."""
    config = _config()

    with MerovingianStore(config.db_path) as store:
        removed = store.unregister_repo(name)

    if removed:
        console.print(f"[green]Unregistered[/green] '{name}'")
    else:
        console.print(f"[yellow]Repository '{name}' not found[/yellow]")
        raise typer.Exit(1)


@app.command()
def repos() -> None:
    """List registered repositories."""
    from rich.table import Table

    config = _config()

    with MerovingianStore(config.db_path) as store:
        repo_list = store.list_repos()

    if not repo_list:
        console.print("[dim]No repositories registered.[/dim]")
        return

    table = Table(title="Registered Repositories")
    table.add_column("Name", style="bold")
    table.add_column("Path")
    table.add_column("Type")
    table.add_column("Registered")

    for r in repo_list:
        table.add_row(
            r.name, r.path,
            r.contract_type.value if r.contract_type else "auto",
            r.registered_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command()
def scan(repo: str) -> None:
    """Scan a repository and update its endpoints."""
    from merovingian.core.scanner import compute_spec_hash, scan_repo

    config = _config()

    with MerovingianStore(config.db_path) as store:
        repo_info = store.get_repo(repo)
        if repo_info is None:
            console.print(f"[red]Repository '{repo}' not registered[/red]")
            raise typer.Exit(1)

        endpoints = scan_repo(repo_info, config.scanner)
        store.delete_endpoints(repo)
        count = store.save_endpoints(endpoints)
        spec_hash = compute_spec_hash(endpoints)

    console.print(f"[green]Scanned[/green] {count} endpoints (hash: {spec_hash[:12]})")


@app.command(name="consumers")
def list_consumers(
    repo: Annotated[Optional[str], typer.Option("--repo", "-r", help="Producer repo")] = None,
    endpoint: Annotated[
        Optional[str], typer.Option("--endpoint", "-e", help="Endpoint as METHOD:PATH")
    ] = None,
) -> None:
    """List consumer relationships."""
    from rich.table import Table

    config = _config()

    with MerovingianStore(config.db_path) as store:
        if repo and endpoint and ":" in endpoint:
            method, path = endpoint.split(":", 1)
            consumers = store.get_consumers_of(repo, method.upper(), path)
        elif repo:
            consumers = store.get_consumers_of_repo(repo)
        else:
            consumers = []
            for r in store.list_repos():
                consumers.extend(store.get_consumers_of_repo(r.name))

    if not consumers:
        console.print("[dim]No consumers found.[/dim]")
        return

    table = Table(title="Consumer Relationships")
    table.add_column("Consumer", style="bold")
    table.add_column("Producer")
    table.add_column("Method")
    table.add_column("Path")

    for c in consumers:
        table.add_row(c.consumer_repo, c.producer_repo, c.endpoint_method, c.endpoint_path)
    console.print(table)


@app.command()
def add_consumer(
    consumer: str,
    producer: str,
    method: str,
    path: str,
) -> None:
    """Register a consumer relationship."""
    from merovingian.core.registry import register_consumer

    config = _config()

    try:
        with MerovingianStore(config.db_path) as store:
            register_consumer(store, consumer, producer, method.upper(), path)
        console.print(
            f"[green]Registered[/green] {consumer} as consumer of "
            f"{producer} {method.upper()} {path}"
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def breaking(repo: str) -> None:
    """Check for breaking changes in a repository."""
    from merovingian.core.impact import check_breaking

    config = _config()

    try:
        with MerovingianStore(config.db_path) as store:
            changes = check_breaking(store, repo, config.scanner)

        if not changes:
            console.print("[green]No breaking changes detected.[/green]")
            return

        console.print(f"[red bold]{len(changes)} breaking change(s) detected:[/red bold]")
        for change in changes:
            console.print(f"  [{change.severity.value}] {change.description}")
            if change.affected_consumers:
                console.print(f"    Affected: {', '.join(change.affected_consumers)}")
    except (sqlite3.Error, OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def impact(repo: str) -> None:
    """Full impact assessment with consumer mapping."""
    from merovingian.core.impact import assess_impact

    config = _config()

    try:
        with MerovingianStore(config.db_path) as store:
            report = assess_impact(store, repo, config.scanner)

        console.print(f"[bold]Impact Report for {repo}[/bold]")
        console.print(f"Report ID: {report.report_id[:8]}")
        console.print(f"Consumers affected: {report.consumer_count}")

        if report.breaking_changes:
            console.print(f"\n[red bold]{len(report.breaking_changes)} Breaking:[/red bold]")
            for bc in report.breaking_changes:
                console.print(f"  [{bc.severity.value}] {bc.description}")

        if report.non_breaking_changes:
            console.print(f"\n[dim]{len(report.non_breaking_changes)} Non-breaking changes[/dim]")

        if not report.breaking_changes and not report.non_breaking_changes:
            console.print("[green]No changes detected.[/green]")
    except (sqlite3.Error, OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def contracts(
    repo: str,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
) -> None:
    """List contract version history for a repository."""
    from rich.table import Table

    config = _config()

    with MerovingianStore(config.db_path) as store:
        versions = store.list_versions(repo, limit=limit)

    if not versions:
        console.print("[dim]No contract versions recorded.[/dim]")
        return

    table = Table(title=f"Contract Versions: {repo}")
    table.add_column("Version", style="bold")
    table.add_column("Hash")
    table.add_column("Endpoints")
    table.add_column("Captured")

    for v in versions:
        table.add_row(
            v.version_id[:8], v.spec_hash[:12],
            str(len(v.endpoints)), v.captured_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@app.command()
def graph(
    repo: Annotated[Optional[str], typer.Argument(help="Repository name")] = None,
) -> None:
    """Show the dependency graph."""
    from merovingian.core.registry import build_dependency_graph

    config = _config()

    with MerovingianStore(config.db_path) as store:
        full_graph = build_dependency_graph(store)

    if repo:
        if repo not in full_graph:
            console.print(f"[yellow]Repository '{repo}' not found in graph[/yellow]")
            raise typer.Exit(1)
        full_graph = {repo: full_graph[repo]}

    if not full_graph:
        console.print("[dim]No repositories registered.[/dim]")
        return

    for name, edges in sorted(full_graph.items()):
        console.print(f"[bold]{name}[/bold]")
        depends_on = edges.get("depends_on", [])
        depended_by = edges.get("depended_by", [])
        if depends_on:
            console.print(f"  depends on: {', '.join(depends_on)}")
        if depended_by:
            console.print(f"  depended by: {', '.join(depended_by)}")
        if not depends_on and not depended_by:
            console.print("  [dim](no dependencies)[/dim]")


@app.command()
def feedback(
    target_id: str,
    outcome: str,
    target_type: Annotated[Optional[str], typer.Option("--type", "-t")] = None,
    context: Annotated[Optional[str], typer.Option("--context", "-c")] = None,
) -> None:
    """Submit feedback on a report or change."""
    from merovingian.models.contracts import Feedback

    config = _config()
    fb = Feedback(
        target_id=target_id,
        target_type=TargetType(target_type) if target_type else TargetType.REPORT,
        outcome=FeedbackOutcome(outcome),
        context=context or "",
    )

    with MerovingianStore(config.db_path) as store:
        store.save_feedback(fb)

    console.print(f"[green]Feedback recorded:[/green] {outcome} for {target_id[:8]}")


@app.command()
def audit(
    tool: Annotated[Optional[str], typer.Option("--tool", "-t")] = None,
    since: Annotated[Optional[int], typer.Option("--since", "-s", help="Minutes ago")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
) -> None:
    """Query the audit log."""
    from datetime import datetime, timedelta, timezone

    from rich.table import Table

    config = _config()
    since_dt = None
    if since:
        since_dt = datetime.now(timezone.utc) - timedelta(minutes=since)

    with MerovingianStore(config.db_path) as store:
        entries = store.query_audit(tool_name=tool, since=since_dt, limit=limit)

    if not entries:
        console.print("[dim]No audit entries found.[/dim]")
        return

    table = Table(title="Audit Log")
    table.add_column("Tool", style="bold")
    table.add_column("Parameters")
    table.add_column("Result")
    table.add_column("Date")

    for entry in entries:
        table.add_row(
            entry.tool_name,
            entry.parameters[:50],
            entry.result_summary[:50],
            entry.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
