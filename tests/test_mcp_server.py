"""Tests for the MCP server tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from merovingian.config import MerovingianConfig
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import Endpoint, RepoInfo
from merovingian.models.enums import ContractType


@pytest.fixture
def config(tmp_path):
    return MerovingianConfig(data_dir=tmp_path)


@pytest.fixture
def initialized_store(config):
    """Create an initialized store with test data."""
    with MerovingianStore(config.db_path) as store:
        store.register_repo(RepoInfo(
            name="user-service", path="/tmp/users",
            contract_type=ContractType.OPENAPI,
        ))
        store.save_endpoints([
            Endpoint(repo_name="user-service", method="GET", path="/users",
                     summary="List users"),
        ])
    return config


@pytest.fixture
def server(config):
    """Create MCP server with test config."""
    from merovingian.mcp.server import create_server
    return create_server(config)


@pytest.fixture
def initialized_server(initialized_store):
    """Create MCP server with pre-populated data."""
    from merovingian.mcp.server import create_server
    return create_server(initialized_store)


class TestMerovingianRegister:
    def test_register_repo(self, server, config):
        tool = server._tool_manager.get_tool("merovingian_register")
        result = tool.fn(name="test-repo", path="/tmp/test")
        assert "Registered" in result

        # Verify in store
        with MerovingianStore(config.db_path) as store:
            repo = store.get_repo("test-repo")
            assert repo is not None

    def test_register_with_type(self, server, config):
        tool = server._tool_manager.get_tool("merovingian_register")
        result = tool.fn(name="api-svc", path="/tmp/api", contract_type="openapi")
        assert "Registered" in result

    def test_register_invalid_type(self, server):
        tool = server._tool_manager.get_tool("merovingian_register")
        result = tool.fn(name="bad", path="/tmp/bad", contract_type="invalid")
        assert "Error" in result


class TestMerovingianScan:
    def test_scan_unregistered(self, server):
        tool = server._tool_manager.get_tool("merovingian_scan")
        result = tool.fn(name="nonexistent")
        assert "Error" in result
        assert "not registered" in result

    def test_scan_registered(self, initialized_server, initialized_store, tmp_path):
        tool = initialized_server._tool_manager.get_tool("merovingian_scan")
        # user-service is registered with path=/tmp/users which doesn't exist, so 0 endpoints
        result = tool.fn(name="user-service")
        assert "Scanned" in result
        assert "user-service" in result


class TestMerovingianAddConsumer:
    def test_add_consumer(self, initialized_server, initialized_store):
        tool = initialized_server._tool_manager.get_tool("merovingian_add_consumer")
        result = tool.fn(
            consumer_repo="billing-service",
            producer_repo="user-service",
            endpoint_method="GET",
            endpoint_path="/users",
        )
        assert "Registered" in result
        assert "billing-service" in result
        assert "user-service" in result

        # Verify it persisted
        with MerovingianStore(initialized_store.db_path) as store:
            consumers = store.get_consumers_of_repo("user-service")
            assert any(c.consumer_repo == "billing-service" for c in consumers)

    def test_add_consumer_normalizes_method(self, initialized_server, initialized_store):
        tool = initialized_server._tool_manager.get_tool("merovingian_add_consumer")
        result = tool.fn(
            consumer_repo="notify-service",
            producer_repo="user-service",
            endpoint_method="get",
            endpoint_path="/users",
        )
        assert "Registered" in result

        with MerovingianStore(initialized_store.db_path) as store:
            consumers = store.get_consumers_of_repo("user-service")
            assert any(c.consumer_repo == "notify-service" for c in consumers)


class TestMerovingianConsumers:
    def test_no_consumers(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_consumers")
        result = tool.fn(producer_repo="user-service")
        assert "No consumers" in result

    def test_with_consumers(self, initialized_store):
        from merovingian.mcp.server import create_server
        from merovingian.models.contracts import Consumer

        with MerovingianStore(initialized_store.db_path) as store:
            store.add_consumer(Consumer(
                consumer_repo="billing", producer_repo="user-service",
                endpoint_method="GET", endpoint_path="/users",
            ))

        server = create_server(initialized_store)
        tool = server._tool_manager.get_tool("merovingian_consumers")
        result = tool.fn(producer_repo="user-service")
        assert "billing" in result


class TestMerovingianBreaking:
    def test_no_breaking(self, initialized_store):
        from merovingian.mcp.server import create_server

        server = create_server(initialized_store)
        tool = server._tool_manager.get_tool("merovingian_breaking")

        current_eps = None
        with MerovingianStore(initialized_store.db_path) as store:
            current_eps = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current_eps):
            result = tool.fn(repo_name="user-service")

        assert "No breaking changes" in result

    def test_nonexistent_repo(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_breaking")
        result = tool.fn(repo_name="nonexistent")
        assert "Error" in result


class TestMerovingianImpact:
    def test_impact_report(self, initialized_store):
        from merovingian.mcp.server import create_server

        server = create_server(initialized_store)
        tool = server._tool_manager.get_tool("merovingian_impact")

        with MerovingianStore(initialized_store.db_path) as store:
            current_eps = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current_eps):
            result = tool.fn(repo_name="user-service")

        assert "Impact Report" in result


class TestMerovingianContracts:
    def test_no_versions(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_contracts")
        result = tool.fn(repo_name="user-service")
        assert "No contract versions" in result


class TestMerovingianGraph:
    def test_graph(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_graph")
        result = tool.fn()
        assert "user-service" in result

    def test_graph_filtered(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_graph")
        result = tool.fn(repo_name="user-service")
        assert "user-service" in result

    def test_graph_nonexistent(self, initialized_server):
        tool = initialized_server._tool_manager.get_tool("merovingian_graph")
        result = tool.fn(repo_name="nonexistent")
        assert "not found" in result


class TestMerovingianFeedback:
    def test_submit(self, initialized_server, initialized_store):
        tool = initialized_server._tool_manager.get_tool("merovingian_feedback")
        result = tool.fn(target_id="abc123", outcome="accepted")
        assert "Feedback recorded" in result

        with MerovingianStore(initialized_store.db_path) as store:
            fb_list = store.list_feedback()
            assert len(fb_list) >= 1


class TestMerovingianAudit:
    def test_audit_empty(self, server):
        tool = server._tool_manager.get_tool("merovingian_audit")
        result = tool.fn()
        assert "No audit" in result
