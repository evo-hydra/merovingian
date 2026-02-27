"""Tests for the impact assessment orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from merovingian.config import ScannerConfig
from merovingian.core.impact import assess_impact, check_breaking
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import Consumer, Endpoint, RepoInfo
from merovingian.models.enums import ChangeKind, ContractType, Severity


@pytest.fixture
def store(tmp_path):
    with MerovingianStore(tmp_path / "test.db") as s:
        s.register_repo(RepoInfo(
            name="user-service", path=str(tmp_path / "user-svc"),
            contract_type=ContractType.OPENAPI,
        ))
        # Save initial endpoints
        s.save_endpoints([
            Endpoint(
                repo_name="user-service", method="GET", path="/users",
                summary="List users",
                response_schema=json.dumps({"id": {"type": "integer"}, "name": {"type": "string"}}),
            ),
            Endpoint(
                repo_name="user-service", method="GET", path="/users/{id}",
                summary="Get user",
                response_schema=json.dumps({"id": {"type": "integer"}, "name": {"type": "string"}}),
            ),
        ])
        # Add a consumer
        s.add_consumer(Consumer(
            consumer_repo="billing", producer_repo="user-service",
            endpoint_method="GET", endpoint_path="/users/{id}",
        ))
        yield s


@pytest.fixture
def config():
    return ScannerConfig()


class TestAssessImpact:
    def test_no_changes(self, store, config):
        """When scan returns same endpoints, no changes detected."""
        current_endpoints = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current_endpoints):
            report = assess_impact(store, "user-service", config)

        assert len(report.breaking_changes) == 0
        assert len(report.non_breaking_changes) == 0
        assert report.consumer_count == 0

    def test_breaking_change_detected(self, store, config):
        """When a response field is removed, it's detected as breaking."""
        new_endpoints = [
            Endpoint(
                repo_name="user-service", method="GET", path="/users",
                response_schema=json.dumps({"id": {"type": "integer"}}),  # name removed
            ),
            Endpoint(
                repo_name="user-service", method="GET", path="/users/{id}",
                response_schema=json.dumps({"id": {"type": "integer"}}),  # name removed
            ),
        ]

        with patch("merovingian.core.impact.scan_repo", return_value=new_endpoints):
            report = assess_impact(store, "user-service", config)

        assert len(report.breaking_changes) >= 1
        # Check affected consumers for /users/{id}
        user_id_changes = [
            bc for bc in report.breaking_changes
            if bc.endpoint_path == "/users/{id}"
        ]
        assert len(user_id_changes) >= 1
        assert "billing" in user_id_changes[0].affected_consumers

    def test_endpoint_removed(self, store, config):
        """When an endpoint is removed, it's detected as breaking."""
        new_endpoints = [
            Endpoint(repo_name="user-service", method="GET", path="/users"),
            # /users/{id} removed
        ]

        with patch("merovingian.core.impact.scan_repo", return_value=new_endpoints):
            report = assess_impact(store, "user-service", config)

        removed = [bc for bc in report.breaking_changes if bc.change_kind == ChangeKind.REMOVED]
        assert len(removed) >= 1

    def test_saves_version(self, store, config):
        current_endpoints = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current_endpoints):
            report = assess_impact(store, "user-service", config)

        versions = store.list_versions("user-service")
        assert len(versions) >= 1

    def test_saves_report(self, store, config):
        current_endpoints = store.get_endpoints("user-service")

        with patch("merovingian.core.impact.scan_repo", return_value=current_endpoints):
            report = assess_impact(store, "user-service", config)

        saved = store.get_report(report.report_id)
        assert saved is not None
        assert saved.repo_name == "user-service"

    def test_nonexistent_repo(self, store, config):
        with pytest.raises(ValueError, match="not registered"):
            assess_impact(store, "nonexistent", config)

    def test_consumer_count(self, store, config):
        """Consumer count reflects unique affected consumers."""
        new_endpoints = [
            Endpoint(
                repo_name="user-service", method="GET", path="/users/{id}",
                response_schema=json.dumps({"id": {"type": "integer"}}),  # name removed
            ),
        ]

        with patch("merovingian.core.impact.scan_repo", return_value=new_endpoints):
            report = assess_impact(store, "user-service", config)

        assert report.consumer_count >= 1


class TestCheckBreaking:
    def test_returns_breaking_only(self, store, config):
        """check_breaking returns only breaking changes, no persistence."""
        new_endpoints = [
            Endpoint(
                repo_name="user-service", method="GET", path="/users",
                response_schema=json.dumps({"id": {"type": "integer"}}),
            ),
            Endpoint(
                repo_name="user-service", method="GET", path="/users/{id}",
                response_schema=json.dumps({"id": {"type": "integer"}}),
            ),
            Endpoint(repo_name="user-service", method="POST", path="/new-endpoint"),
        ]

        with patch("merovingian.core.impact.scan_repo", return_value=new_endpoints):
            changes = check_breaking(store, "user-service", config)

        # Should only return breaking changes (field removals)
        assert all(c.severity == Severity.BREAKING for c in changes)

    def test_nonexistent_repo(self, store, config):
        with pytest.raises(ValueError, match="not registered"):
            check_breaking(store, "nonexistent", config)

    def test_no_breaking_changes(self, store, config):
        current = store.get_endpoints("user-service")
        with patch("merovingian.core.impact.scan_repo", return_value=current):
            changes = check_breaking(store, "user-service", config)
        assert changes == []
