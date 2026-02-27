"""FastMCP server factory with 8 MCP tools."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from merovingian.config import MerovingianConfig
from merovingian.models.contracts import AuditEntry, Feedback, RepoInfo
from merovingian.models.enums import ContractType


def create_server(config: MerovingianConfig | None = None):
    """Create and return a configured FastMCP server instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "merovingian",
        instructions=(
            "Cross-repository dependency intelligence. "
            "Maps API contracts, tracks consumers, and detects breaking changes "
            "across microservice boundaries."
        ),
    )
    _config = config or MerovingianConfig.load()

    def _audit(store, tool_name: str, parameters: dict, result_summary: str) -> None:
        """Log an audit entry for a tool invocation."""
        store.log_audit(AuditEntry(
            tool_name=tool_name,
            parameters=json.dumps(parameters),
            result_summary=result_summary[:200],
        ))

    @mcp.tool()
    def merovingian_register(
        name: str,
        path: str,
        contract_type: str | None = None,
    ) -> str:
        """Register a repository for contract scanning.

        Args:
            name: Unique name for the repository
            path: Filesystem path to the repository root
            contract_type: Contract type: 'openapi' or 'pydantic' (optional, auto-detect if omitted)
        """
        from merovingian.core.store import MerovingianStore

        try:
            ct = ContractType(contract_type) if contract_type else None
            repo = RepoInfo(name=name, path=path, contract_type=ct)

            with MerovingianStore(_config.db_path) as store:
                store.register_repo(repo)
                _audit(store, "merovingian_register",
                       {"name": name, "path": path, "contract_type": contract_type},
                       f"Registered repo '{name}'")

            return f"Registered repository '{name}' at {path}"
        except (sqlite3.Error, OSError, ValueError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_consumers(
        producer_repo: str | None = None,
        endpoint_method: str | None = None,
        endpoint_path: str | None = None,
    ) -> str:
        """List consumers of endpoints.

        Args:
            producer_repo: Filter by producer repository name (optional)
            endpoint_method: Filter by HTTP method (optional)
            endpoint_path: Filter by endpoint path (optional)
        """
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_consumers

        try:
            with MerovingianStore(_config.db_path) as store:
                if producer_repo and endpoint_method and endpoint_path:
                    consumers = store.get_consumers_of(
                        producer_repo, endpoint_method, endpoint_path
                    )
                elif producer_repo:
                    consumers = store.get_consumers_of_repo(producer_repo)
                else:
                    # List all consumers across all repos
                    consumers = []
                    for repo in store.list_repos():
                        consumers.extend(store.get_consumers_of_repo(repo.name))

                result = format_consumers(consumers)
                _audit(store, "merovingian_consumers",
                       {"producer_repo": producer_repo, "endpoint_method": endpoint_method,
                        "endpoint_path": endpoint_path},
                       f"{len(consumers)} consumers found")

            return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_breaking(repo_name: str) -> str:
        """Check for breaking changes in a repository's contracts.

        Args:
            repo_name: Name of the repository to check
        """
        from merovingian.core.impact import check_breaking
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_breaking_changes

        try:
            with MerovingianStore(_config.db_path) as store:
                changes = check_breaking(store, repo_name, _config.scanner)
                result = format_breaking_changes(changes)
                _audit(store, "merovingian_breaking",
                       {"repo_name": repo_name},
                       f"{len(changes)} breaking changes")

            return result
        except (sqlite3.Error, OSError, ValueError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_impact(repo_name: str) -> str:
        """Full impact assessment with consumer mapping for a repository.

        Args:
            repo_name: Name of the repository to assess
        """
        from merovingian.core.impact import assess_impact
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_impact_report

        try:
            with MerovingianStore(_config.db_path) as store:
                report = assess_impact(store, repo_name, _config.scanner)
                result = format_impact_report(report)
                _audit(store, "merovingian_impact",
                       {"repo_name": repo_name},
                       f"{len(report.breaking_changes)} breaking, "
                       f"{len(report.non_breaking_changes)} non-breaking")

            return result
        except (sqlite3.Error, OSError, ValueError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_contracts(
        repo_name: str,
        limit: int | None = None,
    ) -> str:
        """List contract versions for a repository.

        Args:
            repo_name: Name of the repository
            limit: Maximum number of versions to return (optional, default 50)
        """
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_contract_versions

        try:
            with MerovingianStore(_config.db_path) as store:
                versions = store.list_versions(
                    repo_name, limit=limit or _config.mcp.default_query_limit
                )
                result = format_contract_versions(versions)
                _audit(store, "merovingian_contracts",
                       {"repo_name": repo_name, "limit": limit},
                       f"{len(versions)} versions")

            return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_graph(repo_name: str | None = None) -> str:
        """Query the dependency graph.

        Args:
            repo_name: Filter to a specific repository's dependencies (optional)
        """
        from merovingian.core.registry import build_dependency_graph
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_dependency_graph

        try:
            with MerovingianStore(_config.db_path) as store:
                graph = build_dependency_graph(store)

                if repo_name and repo_name in graph:
                    graph = {repo_name: graph[repo_name]}
                elif repo_name:
                    return f"Repository '{repo_name}' not found in dependency graph."

                result = format_dependency_graph(graph)
                _audit(store, "merovingian_graph",
                       {"repo_name": repo_name},
                       f"{len(graph)} repos in graph")

            return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_feedback(
        target_id: str,
        outcome: str,
        target_type: str | None = None,
        context: str | None = None,
    ) -> str:
        """Submit feedback on an assessment or change.

        Args:
            target_id: ID of the report or change to give feedback on
            outcome: One of: accepted, rejected, modified
            target_type: Type of target (e.g., 'report', 'change') (optional)
            context: Explanation of why (optional)
        """
        from merovingian.core.store import MerovingianStore

        try:
            fb = Feedback(
                target_id=target_id,
                target_type=target_type or "report",
                outcome=outcome,
                context=context or "",
            )
            with MerovingianStore(_config.db_path) as store:
                store.save_feedback(fb)
                _audit(store, "merovingian_feedback",
                       {"target_id": target_id, "outcome": outcome},
                       f"Feedback recorded: {outcome}")

            return f"Feedback recorded: {outcome} for {target_id[:8]}"
        except (sqlite3.Error, OSError) as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def merovingian_audit(
        tool_name: str | None = None,
        since: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Query the audit log of tool invocations.

        Args:
            tool_name: Filter by tool name (optional)
            since: Look back N minutes (optional)
            limit: Max entries to return (optional, default 50)
        """
        from merovingian.core.store import MerovingianStore
        from merovingian.mcp.formatters import format_audit

        try:
            since_dt = None
            if since:
                from datetime import timedelta
                since_dt = datetime.now(timezone.utc) - timedelta(minutes=since)

            with MerovingianStore(_config.db_path) as store:
                entries = store.query_audit(
                    tool_name=tool_name,
                    since=since_dt,
                    limit=limit or _config.mcp.default_query_limit,
                )

            return format_audit(entries)
        except (sqlite3.Error, OSError) as exc:
            return f"Error: {exc}"

    return mcp


def main() -> None:
    """Entry point for merovingian-mcp (stdio transport)."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
