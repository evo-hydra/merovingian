"""Tests for the SQLite store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from merovingian.core.store import MerovingianStore
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


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with MerovingianStore(db_path) as s:
        yield s


@pytest.fixture
def populated_store(store):
    """Store with a registered repo and endpoints."""
    repo = RepoInfo(name="user-service", path="/tmp/users", contract_type=ContractType.OPENAPI)
    store.register_repo(repo)
    endpoints = [
        Endpoint(repo_name="user-service", method="GET", path="/users",
                 summary="List users"),
        Endpoint(repo_name="user-service", method="GET", path="/users/{id}",
                 summary="Get user by ID",
                 response_schema='{"name": {"type": "string", "required": true}}'),
        Endpoint(repo_name="user-service", method="POST", path="/users",
                 summary="Create user",
                 request_schema='{"name": {"type": "string", "required": true}}'),
    ]
    store.save_endpoints(endpoints)
    return store


class TestStoreLifecycle:
    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        with MerovingianStore(db_path) as s:
            assert s.conn is not None
        # After exit, conn should be None
        assert s._conn is None

    def test_conn_guard(self, tmp_path):
        s = MerovingianStore(tmp_path / "guard.db")
        with pytest.raises(RuntimeError, match="Store is not open"):
            _ = s.conn

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "test.db"
        with MerovingianStore(db_path) as s:
            assert db_path.exists()

    def test_schema_version(self, store):
        assert store.get_meta("schema_version") == "1"


class TestMeta:
    def test_set_and_get(self, store):
        store.set_meta("test_key", "test_value")
        assert store.get_meta("test_key") == "test_value"

    def test_get_missing(self, store):
        assert store.get_meta("nonexistent") is None

    def test_upsert(self, store):
        store.set_meta("key", "v1")
        store.set_meta("key", "v2")
        assert store.get_meta("key") == "v2"


class TestRepos:
    def test_register_and_get(self, store):
        repo = RepoInfo(name="test-repo", path="/tmp/test", contract_type=ContractType.OPENAPI)
        store.register_repo(repo)
        result = store.get_repo("test-repo")
        assert result is not None
        assert result.name == "test-repo"
        assert result.contract_type == ContractType.OPENAPI

    def test_get_missing(self, store):
        assert store.get_repo("nonexistent") is None

    def test_list_repos(self, store):
        store.register_repo(RepoInfo(name="a", path="/a"))
        store.register_repo(RepoInfo(name="b", path="/b"))
        repos = store.list_repos()
        assert len(repos) == 2
        assert repos[0].name == "a"

    def test_unregister(self, store):
        store.register_repo(RepoInfo(name="x", path="/x"))
        assert store.unregister_repo("x") is True
        assert store.get_repo("x") is None

    def test_unregister_nonexistent(self, store):
        assert store.unregister_repo("nope") is False

    def test_register_no_contract_type(self, store):
        repo = RepoInfo(name="auto", path="/auto")
        store.register_repo(repo)
        result = store.get_repo("auto")
        assert result is not None
        assert result.contract_type is None


class TestEndpoints:
    def test_save_and_get(self, populated_store):
        endpoints = populated_store.get_endpoints("user-service")
        assert len(endpoints) == 3

    def test_get_empty(self, store):
        assert store.get_endpoints("nonexistent") == []

    def test_upsert(self, populated_store):
        # Saving same endpoint again should update (not duplicate)
        ep = Endpoint(repo_name="user-service", method="GET", path="/users",
                      summary="Updated summary")
        populated_store.save_endpoints([ep])
        endpoints = populated_store.get_endpoints("user-service")
        get_users = [e for e in endpoints if e.method == "GET" and e.path == "/users"]
        assert len(get_users) == 1
        assert get_users[0].summary == "Updated summary"

    def test_delete_endpoints(self, populated_store):
        count = populated_store.delete_endpoints("user-service")
        assert count == 3
        assert populated_store.get_endpoints("user-service") == []

    def test_search_endpoints(self, populated_store):
        results = populated_store.search_endpoints("users")
        assert len(results) >= 1

    def test_search_no_results(self, populated_store):
        results = populated_store.search_endpoints("zzzznonexistent")
        assert results == []


class TestConsumers:
    def test_add_and_get(self, populated_store):
        consumer = Consumer(
            consumer_repo="billing", producer_repo="user-service",
            endpoint_method="GET", endpoint_path="/users/{id}",
        )
        populated_store.add_consumer(consumer)
        consumers = populated_store.get_consumers_of("user-service", "GET", "/users/{id}")
        assert len(consumers) == 1
        assert consumers[0].consumer_repo == "billing"

    def test_get_consumers_of_repo(self, populated_store):
        populated_store.add_consumer(Consumer(
            consumer_repo="billing", producer_repo="user-service",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))
        populated_store.add_consumer(Consumer(
            consumer_repo="auth", producer_repo="user-service",
            endpoint_method="GET", endpoint_path="/users",
        ))
        consumers = populated_store.get_consumers_of_repo("user-service")
        assert len(consumers) == 2

    def test_remove_consumer(self, populated_store):
        populated_store.add_consumer(Consumer(
            consumer_repo="billing", producer_repo="user-service",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))
        removed = populated_store.remove_consumer(
            "billing", "user-service", "GET", "/users/{id}"
        )
        assert removed is True
        assert populated_store.get_consumers_of("user-service", "GET", "/users/{id}") == []

    def test_remove_nonexistent(self, store):
        assert store.remove_consumer("a", "b", "GET", "/x") is False


class TestContractVersions:
    def test_save_and_get_latest(self, populated_store):
        ep = Endpoint(repo_name="user-service", method="GET", path="/users")
        version = ContractVersion(
            repo_name="user-service", spec_hash="abc123", endpoints=(ep,)
        )
        populated_store.save_version(version)

        latest = populated_store.get_latest_version("user-service")
        assert latest is not None
        assert latest.spec_hash == "abc123"
        assert len(latest.endpoints) == 1

    def test_get_latest_none(self, store):
        assert store.get_latest_version("nonexistent") is None

    def test_list_versions(self, populated_store):
        for i in range(3):
            v = ContractVersion(repo_name="user-service", spec_hash=f"hash{i}")
            populated_store.save_version(v)

        versions = populated_store.list_versions("user-service")
        assert len(versions) == 3


class TestImpactReports:
    def test_save_and_get(self, populated_store):
        bc = BreakingChange(
            repo_name="user-service", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed", affected_consumers=("billing",),
        )
        report = ImpactReport(
            repo_name="user-service",
            breaking_changes=(bc,),
            consumer_count=1,
        )
        populated_store.save_report(report)

        result = populated_store.get_report(report.report_id)
        assert result is not None
        assert len(result.breaking_changes) == 1
        assert result.breaking_changes[0].affected_consumers == ("billing",)
        assert result.consumer_count == 1

    def test_list_reports(self, populated_store):
        for _ in range(2):
            populated_store.save_report(ImpactReport(repo_name="user-service"))
        reports = populated_store.list_reports("user-service")
        assert len(reports) == 2

    def test_get_missing(self, store):
        assert store.get_report("nonexistent") is None


class TestFeedback:
    def test_save_and_list(self, store):
        fb = Feedback(target_id="rpt123", target_type="report", outcome="accepted", context="LGTM")
        store.save_feedback(fb)
        entries = store.list_feedback()
        assert len(entries) == 1
        assert entries[0].outcome == "accepted"


class TestAudit:
    def test_log_and_query(self, store):
        entry = AuditEntry(
            tool_name="merovingian_register",
            parameters='{"name": "test"}',
            result_summary="Registered repo 'test'",
        )
        store.log_audit(entry)
        results = store.query_audit()
        assert len(results) == 1
        assert results[0].tool_name == "merovingian_register"

    def test_query_filter_by_tool(self, store):
        store.log_audit(AuditEntry(tool_name="tool_a", parameters="{}", result_summary="ok"))
        store.log_audit(AuditEntry(tool_name="tool_b", parameters="{}", result_summary="ok"))
        results = store.query_audit(tool_name="tool_a")
        assert len(results) == 1
        assert results[0].tool_name == "tool_a"

    def test_query_with_limit(self, store):
        for i in range(10):
            store.log_audit(AuditEntry(tool_name=f"tool_{i}", parameters="{}", result_summary="ok"))
        results = store.query_audit(limit=3)
        assert len(results) == 3
