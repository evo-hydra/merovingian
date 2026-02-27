"""Tests for the consumer registry."""

from __future__ import annotations

import pytest

from merovingian.core.registry import (
    build_dependency_graph,
    get_affected_consumers,
    register_consumer,
)
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import (
    BreakingChange,
    Consumer,
    Endpoint,
    RepoInfo,
)
from merovingian.models.enums import ChangeKind, ContractType, Severity


@pytest.fixture
def store(tmp_path):
    with MerovingianStore(tmp_path / "test.db") as s:
        # Register repos
        s.register_repo(RepoInfo(name="users", path="/tmp/users", contract_type=ContractType.OPENAPI))
        s.register_repo(RepoInfo(name="billing", path="/tmp/billing"))
        s.register_repo(RepoInfo(name="auth", path="/tmp/auth"))

        # Add endpoints
        s.save_endpoints([
            Endpoint(repo_name="users", method="GET", path="/users"),
            Endpoint(repo_name="users", method="GET", path="/users/{id}"),
            Endpoint(repo_name="users", method="POST", path="/users"),
        ])
        yield s


class TestRegisterConsumer:
    def test_register_valid(self, store):
        consumer = register_consumer(store, "billing", "users", "GET", "/users/{id}")
        assert consumer.consumer_repo == "billing"
        assert consumer.producer_repo == "users"

    def test_register_nonexistent_endpoint(self, store):
        with pytest.raises(ValueError, match="not found"):
            register_consumer(store, "billing", "users", "DELETE", "/users/{id}")

    def test_persists(self, store):
        register_consumer(store, "billing", "users", "GET", "/users/{id}")
        consumers = store.get_consumers_of("users", "GET", "/users/{id}")
        assert len(consumers) == 1


class TestGetAffectedConsumers:
    def test_with_consumers(self, store):
        store.add_consumer(Consumer(
            consumer_repo="billing", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))
        store.add_consumer(Consumer(
            consumer_repo="auth", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))

        changes = [BreakingChange(
            repo_name="users", endpoint_method="GET", endpoint_path="/users/{id}",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed",
        )]

        result = get_affected_consumers(store, changes)
        assert len(result) == 1
        consumers = list(result.values())[0]
        assert set(consumers) == {"billing", "auth"}

    def test_no_consumers(self, store):
        changes = [BreakingChange(
            repo_name="users", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.MODIFIED, severity=Severity.BREAKING,
            description="Field changed",
        )]
        result = get_affected_consumers(store, changes)
        assert result[changes[0]] == []

    def test_empty_changes(self, store):
        result = get_affected_consumers(store, [])
        assert result == {}


class TestBuildDependencyGraph:
    def test_empty_graph(self, store):
        graph = build_dependency_graph(store)
        assert "users" in graph
        assert "billing" in graph
        assert graph["users"]["depends_on"] == []
        assert graph["users"]["depended_by"] == []

    def test_with_consumers(self, store):
        store.add_consumer(Consumer(
            consumer_repo="billing", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))
        store.add_consumer(Consumer(
            consumer_repo="auth", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users",
        ))

        graph = build_dependency_graph(store)

        assert "users" in graph["billing"]["depends_on"]
        assert "users" in graph["auth"]["depends_on"]
        assert set(graph["users"]["depended_by"]) == {"billing", "auth"}

    def test_unregistered_consumer_in_graph(self, store):
        """Consumer repos not explicitly registered should still appear in graph."""
        store.add_consumer(Consumer(
            consumer_repo="external-svc", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users",
        ))
        graph = build_dependency_graph(store)
        assert "external-svc" in graph
        assert "users" in graph["external-svc"]["depends_on"]
