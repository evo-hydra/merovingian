"""Markdown formatters for LLM consumption."""

from __future__ import annotations

from merovingian.models.contracts import (
    AuditEntry,
    ContractChange,
    Consumer,
    ContractVersion,
    Endpoint,
    Feedback,
    ImpactReport,
    RepoInfo,
)


def format_impact_report(report: ImpactReport) -> str:
    """Format an impact report as markdown."""
    lines = [
        f"# Impact Report: {report.repo_name}",
        f"**Report ID:** `{report.report_id[:8]}`",
        f"**Created:** {report.created_at.isoformat()}",
        f"**Consumers affected:** {report.consumer_count}",
        "",
    ]

    if report.breaking_changes:
        lines.append("## Breaking Changes")
        lines.append("")
        lines.append(format_breaking_changes(list(report.breaking_changes)))
        lines.append("")

    if report.non_breaking_changes:
        lines.append("## Non-Breaking Changes")
        lines.append("")
        for change in report.non_breaking_changes:
            lines.append(f"- **{change.severity.value.upper()}** {change.description}")
        lines.append("")

    if not report.breaking_changes and not report.non_breaking_changes:
        lines.append("*No changes detected.*")

    return "\n".join(lines)


def format_breaking_changes(changes: list[ContractChange]) -> str:
    """Format breaking changes as a severity-tagged list."""
    if not changes:
        return "*No breaking changes detected.*"

    lines: list[str] = []
    for change in changes:
        severity_tag = f"[{change.severity.value.upper()}]"
        line = f"- {severity_tag} {change.description}"
        if change.affected_consumers:
            consumers_str = ", ".join(change.affected_consumers)
            line += f"\n  - Affected consumers: {consumers_str}"
        lines.append(line)

    return "\n".join(lines)


def format_consumers(consumers: list[Consumer], endpoint: str | None = None) -> str:
    """Format consumer relationships as a markdown table."""
    if not consumers:
        return "*No consumers registered.*"

    lines = [
        "| Consumer | Producer | Method | Path | Registered |",
        "|----------|----------|--------|------|------------|",
    ]
    for c in consumers:
        lines.append(
            f"| {c.consumer_repo} | {c.producer_repo} | "
            f"{c.endpoint_method} | {c.endpoint_path} | "
            f"{c.registered_at.strftime('%Y-%m-%d')} |"
        )

    return "\n".join(lines)


def format_endpoints(endpoints: list[Endpoint]) -> str:
    """Format endpoints as a markdown table."""
    if not endpoints:
        return "*No endpoints found.*"

    lines = [
        "| Method | Path | Summary |",
        "|--------|------|---------|",
    ]
    for ep in endpoints:
        summary = ep.summary or ""
        lines.append(f"| {ep.method} | {ep.path} | {summary} |")

    return "\n".join(lines)


def format_contract_versions(versions: list[ContractVersion]) -> str:
    """Format contract version history."""
    if not versions:
        return "*No contract versions recorded.*"

    lines = [
        "| Version | Hash | Endpoints | Captured |",
        "|---------|------|-----------|----------|",
    ]
    for v in versions:
        lines.append(
            f"| `{v.version_id[:8]}` | `{v.spec_hash[:12]}` | "
            f"{len(v.endpoints)} | {v.captured_at.strftime('%Y-%m-%d %H:%M')} |"
        )

    return "\n".join(lines)


def format_dependency_graph(graph: dict[str, dict[str, list[str]]]) -> str:
    """Format dependency graph as readable adjacency list."""
    if not graph:
        return "*No repositories registered.*"

    lines: list[str] = []
    for repo, edges in sorted(graph.items()):
        depends_on = edges.get("depends_on", [])
        depended_by = edges.get("depended_by", [])

        lines.append(f"**{repo}**")
        if depends_on:
            lines.append(f"  depends on: {', '.join(depends_on)}")
        if depended_by:
            lines.append(f"  depended by: {', '.join(depended_by)}")
        if not depends_on and not depended_by:
            lines.append("  (no dependencies)")
        lines.append("")

    return "\n".join(lines)


def format_repos(repos: list[RepoInfo]) -> str:
    """Format registered repositories as a markdown table."""
    if not repos:
        return "*No repositories registered.*"

    lines = [
        "| Name | Path | Type | Registered |",
        "|------|------|------|------------|",
    ]
    for r in repos:
        contract_type = r.contract_type.value if r.contract_type else "auto"
        lines.append(
            f"| {r.name} | {r.path} | {contract_type} | "
            f"{r.registered_at.strftime('%Y-%m-%d')} |"
        )

    return "\n".join(lines)


def format_feedback(entries: list[Feedback]) -> str:
    """Format feedback entries."""
    if not entries:
        return "*No feedback recorded.*"

    lines = [
        "| Target | Type | Outcome | Context | Date |",
        "|--------|------|---------|---------|------|",
    ]
    for fb in entries:
        context = fb.context[:50] + "..." if len(fb.context) > 50 else fb.context
        lines.append(
            f"| `{fb.target_id[:8]}` | {fb.target_type.value} | {fb.outcome.value} | "
            f"{context} | {fb.created_at.strftime('%Y-%m-%d')} |"
        )

    return "\n".join(lines)


def format_audit(entries: list[AuditEntry]) -> str:
    """Format audit log entries."""
    if not entries:
        return "*No audit entries.*"

    lines = [
        "| Tool | Parameters | Result | Date |",
        "|------|-----------|--------|------|",
    ]
    for entry in entries:
        params = entry.parameters[:40] + "..." if len(entry.parameters) > 40 else entry.parameters
        result = (
            entry.result_summary[:40] + "..."
            if len(entry.result_summary) > 40
            else entry.result_summary
        )
        lines.append(
            f"| {entry.tool_name} | {params} | {result} | "
            f"{entry.created_at.strftime('%Y-%m-%d %H:%M')} |"
        )

    return "\n".join(lines)
