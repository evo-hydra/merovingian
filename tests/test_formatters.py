"""Tests for markdown formatters."""

from __future__ import annotations

from datetime import datetime, timezone

from merovingian.mcp.formatters import (
    format_audit,
    format_breaking_changes,
    format_consumers,
    format_contract_versions,
    format_dependency_graph,
    format_endpoints,
    format_feedback,
    format_impact_report,
    format_repos,
)
from merovingian.models.contracts import (
    AuditEntry,
    BreakingChange,
    Consumer,
    ContractVersion,
    Endpoint,
    Feedback,
    ImpactReport,
    RepoInfo,
)
from merovingian.models.enums import ChangeKind, ContractType, Severity

NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestFormatImpactReport:
    def test_with_changes(self):
        bc = BreakingChange(
            repo_name="svc", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed", affected_consumers=("billing",),
        )
        report = ImpactReport(
            repo_name="svc", breaking_changes=(bc,), consumer_count=1, created_at=NOW,
        )
        result = format_impact_report(report)
        assert "Impact Report: svc" in result
        assert "Breaking Changes" in result
        assert "Endpoint removed" in result

    def test_no_changes(self):
        report = ImpactReport(repo_name="svc", created_at=NOW)
        result = format_impact_report(report)
        assert "No changes detected" in result

    def test_non_breaking_only(self):
        nb = BreakingChange(
            repo_name="svc", endpoint_method="POST", endpoint_path="/users",
            change_kind=ChangeKind.ADDED, severity=Severity.INFO,
            description="Endpoint added",
        )
        report = ImpactReport(repo_name="svc", non_breaking_changes=(nb,), created_at=NOW)
        result = format_impact_report(report)
        assert "Non-Breaking Changes" in result


class TestFormatBreakingChanges:
    def test_empty(self):
        result = format_breaking_changes([])
        assert "No breaking changes" in result

    def test_with_consumers(self):
        bc = BreakingChange(
            repo_name="svc", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed", affected_consumers=("billing", "auth"),
        )
        result = format_breaking_changes([bc])
        assert "billing" in result
        assert "auth" in result


class TestFormatConsumers:
    def test_empty(self):
        assert "No consumers" in format_consumers([])

    def test_table(self):
        c = Consumer(
            consumer_repo="billing", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users/{id}",
            registered_at=NOW,
        )
        result = format_consumers([c])
        assert "billing" in result
        assert "users" in result
        assert "GET" in result


class TestFormatEndpoints:
    def test_empty(self):
        assert "No endpoints" in format_endpoints([])

    def test_table(self):
        ep = Endpoint(repo_name="svc", method="GET", path="/users", summary="List users")
        result = format_endpoints([ep])
        assert "GET" in result
        assert "/users" in result
        assert "List users" in result


class TestFormatContractVersions:
    def test_empty(self):
        assert "No contract versions" in format_contract_versions([])

    def test_table(self):
        v = ContractVersion(
            repo_name="svc", version_id="a" * 32, spec_hash="b" * 64,
            captured_at=NOW,
        )
        result = format_contract_versions([v])
        assert "aaaaaaaa" in result
        assert "bbbbbbbbbbbb" in result


class TestFormatDependencyGraph:
    def test_empty(self):
        assert "No repositories" in format_dependency_graph({})

    def test_with_deps(self):
        graph = {
            "billing": {"depends_on": ["users"], "depended_by": []},
            "users": {"depends_on": [], "depended_by": ["billing"]},
        }
        result = format_dependency_graph(graph)
        assert "billing" in result
        assert "depends on: users" in result
        assert "depended by: billing" in result

    def test_isolated_node(self):
        graph = {"lonely": {"depends_on": [], "depended_by": []}}
        result = format_dependency_graph(graph)
        assert "no dependencies" in result


class TestFormatRepos:
    def test_empty(self):
        assert "No repositories" in format_repos([])

    def test_table(self):
        repo = RepoInfo(name="svc", path="/tmp/svc", contract_type=ContractType.OPENAPI,
                        registered_at=NOW)
        result = format_repos([repo])
        assert "svc" in result
        assert "openapi" in result


class TestFormatFeedback:
    def test_empty(self):
        assert "No feedback" in format_feedback([])

    def test_entries(self):
        fb = Feedback(target_id="abc123def456", target_type="report",
                      outcome="accepted", context="Good", created_at=NOW)
        result = format_feedback([fb])
        assert "accepted" in result
        assert "abc123de" in result


class TestFormatAudit:
    def test_empty(self):
        assert "No audit" in format_audit([])

    def test_entries(self):
        entry = AuditEntry(
            tool_name="merovingian_register",
            parameters='{"name": "svc"}',
            result_summary="Registered",
            created_at=NOW,
        )
        result = format_audit([entry])
        assert "merovingian_register" in result
        assert "Registered" in result
