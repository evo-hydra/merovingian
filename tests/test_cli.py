"""Tests for the CLI app."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from merovingian.cli.app import app
from merovingian.config import MerovingianConfig
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import Consumer, Endpoint, RepoInfo
from merovingian.models.enums import ContractType

runner = CliRunner()


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Patch _config to use tmp_path."""
    cfg = MerovingianConfig(project_path=tmp_path)

    def mock_config():
        return cfg

    monkeypatch.setattr("merovingian.cli.app._config", mock_config)
    return cfg


@pytest.fixture
def populated(config):
    """Store with test data."""
    with MerovingianStore(config.db_path) as store:
        store.register_repo(RepoInfo(
            name="user-service", path="/tmp/users",
            contract_type=ContractType.OPENAPI,
        ))
        store.save_endpoints([
            Endpoint(repo_name="user-service", method="GET", path="/users",
                     summary="List users",
                     response_schema=json.dumps({"id": {"type": "integer"}})),
            Endpoint(repo_name="user-service", method="GET", path="/users/{id}",
                     summary="Get user"),
        ])
    return config


class TestRegister:
    def test_register(self, config):
        result = runner.invoke(app, ["register", "test-svc", "/tmp/test"])
        assert result.exit_code == 0
        assert "Registered" in result.output

    def test_register_with_type(self, config):
        result = runner.invoke(app, ["register", "api", "/tmp/api", "--type", "openapi"])
        assert result.exit_code == 0


class TestUnregister:
    def test_unregister(self, populated):
        result = runner.invoke(app, ["unregister", "user-service"])
        assert result.exit_code == 0
        assert "Unregistered" in result.output

    def test_unregister_missing(self, config):
        result = runner.invoke(app, ["unregister", "nonexistent"])
        assert result.exit_code == 1


class TestRepos:
    def test_list_repos(self, populated):
        result = runner.invoke(app, ["repos"])
        assert result.exit_code == 0
        assert "user-service" in result.output

    def test_empty_repos(self, config):
        result = runner.invoke(app, ["repos"])
        assert result.exit_code == 0
        assert "No repositories" in result.output


class TestScan:
    def test_scan(self, populated):
        mock_endpoints = [
            Endpoint(repo_name="user-service", method="GET", path="/users"),
        ]
        with patch("merovingian.core.scanner.scan_repo", return_value=mock_endpoints):
            result = runner.invoke(app, ["scan", "user-service"])
        assert result.exit_code == 0
        assert "Scanned" in result.output

    def test_scan_missing_repo(self, config):
        result = runner.invoke(app, ["scan", "nonexistent"])
        assert result.exit_code == 1


class TestConsumers:
    def test_list_consumers(self, populated):
        with MerovingianStore(populated.db_path) as store:
            store.add_consumer(Consumer(
                consumer_repo="billing", producer_repo="user-service",
                endpoint_method="GET", endpoint_path="/users/{id}",
            ))

        result = runner.invoke(app, ["consumers", "--repo", "user-service"])
        assert result.exit_code == 0
        assert "billing" in result.output

    def test_no_consumers(self, populated):
        result = runner.invoke(app, ["consumers", "--repo", "user-service"])
        assert result.exit_code == 0
        assert "No consumers" in result.output


class TestAddConsumer:
    def test_add_consumer(self, populated):
        result = runner.invoke(app, [
            "add-consumer", "billing", "user-service", "GET", "/users/{id}"
        ])
        assert result.exit_code == 0
        assert "Registered" in result.output

    def test_add_consumer_invalid_endpoint(self, populated):
        result = runner.invoke(app, [
            "add-consumer", "billing", "user-service", "DELETE", "/nonexistent"
        ])
        assert result.exit_code == 1


class TestBreaking:
    def test_no_breaking(self, populated):
        current = None
        with MerovingianStore(populated.db_path) as store:
            current = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current):
            result = runner.invoke(app, ["breaking", "user-service"])
        assert result.exit_code == 0
        assert "No breaking changes" in result.output

    def test_with_breaking(self, populated):
        new_eps = [
            Endpoint(repo_name="user-service", method="GET", path="/users"),
            # /users/{id} removed
        ]
        with patch("merovingian.core.impact.scan_repo", return_value=new_eps):
            result = runner.invoke(app, ["breaking", "user-service"])
        assert result.exit_code == 0
        assert "breaking change" in result.output.lower()


class TestImpact:
    def test_impact(self, populated):
        current = None
        with MerovingianStore(populated.db_path) as store:
            current = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current):
            result = runner.invoke(app, ["impact", "user-service"])
        assert result.exit_code == 0
        assert "Impact Report" in result.output

    def test_impact_missing_repo(self, config):
        result = runner.invoke(app, ["impact", "nonexistent"])
        assert result.exit_code == 1


class TestContracts:
    def test_no_versions(self, populated):
        result = runner.invoke(app, ["contracts", "user-service"])
        assert result.exit_code == 0
        assert "No contract versions" in result.output


class TestGraph:
    def test_graph(self, populated):
        result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "user-service" in result.output

    def test_graph_filtered(self, populated):
        result = runner.invoke(app, ["graph", "user-service"])
        assert result.exit_code == 0

    def test_graph_missing(self, populated):
        result = runner.invoke(app, ["graph", "nonexistent"])
        assert result.exit_code == 1


class TestFeedback:
    def test_submit_feedback(self, config):
        result = runner.invoke(app, ["feedback", "abc123", "accepted"])
        assert result.exit_code == 0
        assert "Feedback recorded" in result.output


class TestAudit:
    def test_empty_audit(self, config):
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "No audit entries" in result.output
