"""Tests for frozen dataclass models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from merovingian.models.contracts import (
    AuditEntry,
    ContractChange,
    Consumer,
    ContractVersion,
    Endpoint,
    Feedback,
    ImpactReport,
    RepoInfo,
    SchemaField,
)
from merovingian.models.enums import ChangeKind, ContractType, FeedbackOutcome, Severity, TargetType


class TestEnums:
    def test_change_kind_values(self):
        assert ChangeKind.ADDED.value == "added"
        assert ChangeKind.REMOVED.value == "removed"
        assert ChangeKind.MODIFIED.value == "modified"
        assert ChangeKind.RENAMED.value == "renamed"

    def test_severity_values(self):
        assert Severity.BREAKING.value == "breaking"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_contract_type_values(self):
        assert ContractType.OPENAPI.value == "openapi"
        assert ContractType.PYDANTIC.value == "pydantic"

    def test_str_enum_behavior(self):
        assert str(ChangeKind.ADDED) == "ChangeKind.ADDED"
        assert ChangeKind("added") == ChangeKind.ADDED


class TestRepoInfo:
    def test_creation(self):
        repo = RepoInfo(name="test", path="/tmp/test")
        assert repo.name == "test"
        assert repo.path == "/tmp/test"
        assert repo.contract_type is None
        assert isinstance(repo.registered_at, datetime)

    def test_with_contract_type(self):
        repo = RepoInfo(name="test", path="/tmp", contract_type=ContractType.OPENAPI)
        assert repo.contract_type == ContractType.OPENAPI

    def test_frozen(self):
        repo = RepoInfo(name="test", path="/tmp")
        with pytest.raises(AttributeError):
            repo.name = "changed"  # type: ignore[misc]


class TestEndpoint:
    def test_creation(self):
        ep = Endpoint(repo_name="svc", method="GET", path="/users")
        assert ep.repo_name == "svc"
        assert ep.method == "GET"
        assert ep.path == "/users"
        assert ep.summary is None

    def test_with_schemas(self):
        ep = Endpoint(
            repo_name="svc", method="POST", path="/users",
            request_schema='{"name": {"type": "string"}}',
            response_schema='{"id": {"type": "integer"}}',
        )
        assert ep.request_schema is not None
        assert ep.response_schema is not None


class TestSchemaField:
    def test_defaults(self):
        field = SchemaField(name="email", field_type="string")
        assert field.required is True
        assert field.default is None

    def test_optional(self):
        field = SchemaField(name="nickname", field_type="string", required=False, default="anon")
        assert field.required is False
        assert field.default == "anon"


class TestConsumer:
    def test_creation(self):
        c = Consumer(
            consumer_repo="billing", producer_repo="users",
            endpoint_method="GET", endpoint_path="/users/{id}",
        )
        assert c.consumer_repo == "billing"
        assert isinstance(c.registered_at, datetime)


class TestContractVersion:
    def test_defaults(self):
        v = ContractVersion(repo_name="svc")
        assert len(v.version_id) == 32  # UUID hex
        assert v.endpoints == ()
        assert v.spec_hash == ""

    def test_with_endpoints(self):
        ep = Endpoint(repo_name="svc", method="GET", path="/test")
        v = ContractVersion(repo_name="svc", endpoints=(ep,))
        assert len(v.endpoints) == 1

    def test_tuple_immutability(self):
        v = ContractVersion(repo_name="svc", endpoints=())
        with pytest.raises(AttributeError):
            v.endpoints.append(None)  # type: ignore[attr-defined]


class TestContractChange:
    def test_creation(self):
        bc = ContractChange(
            repo_name="svc", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed",
        )
        assert bc.affected_consumers == ()

    def test_with_consumers(self):
        bc = ContractChange(
            repo_name="svc", endpoint_method="GET", endpoint_path="/users",
            change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
            description="Endpoint removed",
            affected_consumers=("billing", "auth"),
        )
        assert len(bc.affected_consumers) == 2


class TestImpactReport:
    def test_defaults(self):
        report = ImpactReport(repo_name="svc")
        assert len(report.report_id) == 32
        assert report.breaking_changes == ()
        assert report.non_breaking_changes == ()
        assert report.consumer_count == 0


class TestFeedback:
    def test_creation(self):
        fb = Feedback(target_id="abc123", target_type=TargetType.REPORT, outcome=FeedbackOutcome.ACCEPTED)
        assert fb.context == ""
        assert isinstance(fb.created_at, datetime)
        assert fb.target_type == TargetType.REPORT
        assert fb.outcome == FeedbackOutcome.ACCEPTED

    def test_defaults(self):
        fb = Feedback(target_id="abc123")
        assert fb.target_type == TargetType.REPORT
        assert fb.outcome == FeedbackOutcome.ACCEPTED

    def test_enum_values(self):
        fb = Feedback(target_id="x", target_type=TargetType.CHANGE, outcome=FeedbackOutcome.REJECTED)
        assert fb.target_type.value == "change"
        assert fb.outcome.value == "rejected"


class TestAuditEntry:
    def test_creation(self):
        entry = AuditEntry(
            tool_name="test_tool", parameters="{}", result_summary="ok"
        )
        assert entry.tool_name == "test_tool"
        assert isinstance(entry.created_at, datetime)
