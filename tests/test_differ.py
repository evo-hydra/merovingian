"""Tests for the spec diff engine."""

from __future__ import annotations

import json

import pytest

from merovingian.core.differ import diff_endpoints
from merovingian.models.contracts import Endpoint
from merovingian.models.enums import ChangeKind, Severity


def _ep(method="GET", path="/test", req=None, resp=None, summary=None):
    """Helper to create test endpoints."""
    return Endpoint(
        repo_name="svc",
        method=method,
        path=path,
        summary=summary,
        request_schema=json.dumps(req) if req else None,
        response_schema=json.dumps(resp) if resp else None,
    )


class TestEndpointLevelChanges:
    def test_no_changes(self):
        old = [_ep(method="GET", path="/users")]
        new = [_ep(method="GET", path="/users")]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert non_breaking == []

    def test_endpoint_removed(self):
        old = [_ep(method="GET", path="/users")]
        new = []
        breaking, non_breaking = diff_endpoints(old, new)
        assert len(breaking) == 1
        assert breaking[0].change_kind == ChangeKind.REMOVED
        assert breaking[0].severity == Severity.BREAKING

    def test_endpoint_added(self):
        old = []
        new = [_ep(method="GET", path="/users")]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1
        assert non_breaking[0].change_kind == ChangeKind.ADDED
        assert non_breaking[0].severity == Severity.INFO

    def test_multiple_removed(self):
        old = [_ep(path="/a"), _ep(path="/b"), _ep(path="/c")]
        new = [_ep(path="/a")]
        breaking, _ = diff_endpoints(old, new)
        assert len(breaking) == 2

    def test_summary_change(self):
        old = [_ep(summary="Old summary")]
        new = [_ep(summary="New summary")]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1
        assert non_breaking[0].severity == Severity.INFO


class TestRequestSchemaChanges:
    def test_required_field_added_is_breaking(self):
        old = [_ep(req={"name": {"type": "string", "required": True}})]
        new = [_ep(req={
            "name": {"type": "string", "required": True},
            "email": {"type": "string", "required": True},
        })]
        breaking, _ = diff_endpoints(old, new)
        assert len(breaking) == 1
        assert "email" in breaking[0].description
        assert breaking[0].severity == Severity.BREAKING

    def test_optional_field_added_is_not_breaking(self):
        old = [_ep(req={"name": {"type": "string", "required": True}})]
        new = [_ep(req={
            "name": {"type": "string", "required": True},
            "nickname": {"type": "string", "required": False},
        })]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1
        assert non_breaking[0].severity == Severity.INFO

    def test_request_field_removed_is_not_breaking(self):
        old = [_ep(req={"name": {"type": "string"}, "age": {"type": "integer"}})]
        new = [_ep(req={"name": {"type": "string"}})]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1  # Removing a request field is INFO


class TestResponseSchemaChanges:
    def test_response_field_removed_is_breaking(self):
        old = [_ep(resp={"id": {"type": "integer"}, "name": {"type": "string"}})]
        new = [_ep(resp={"id": {"type": "integer"}})]
        breaking, _ = diff_endpoints(old, new)
        assert len(breaking) == 1
        assert "name" in breaking[0].description
        assert breaking[0].severity == Severity.BREAKING

    def test_response_field_added_is_not_breaking(self):
        old = [_ep(resp={"id": {"type": "integer"}})]
        new = [_ep(resp={"id": {"type": "integer"}, "email": {"type": "string"}})]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1


class TestTypeChanges:
    def test_type_change_is_breaking(self):
        old = [_ep(resp={"age": {"type": "integer"}})]
        new = [_ep(resp={"age": {"type": "string"}})]
        breaking, _ = diff_endpoints(old, new)
        assert len(breaking) == 1
        assert breaking[0].severity == Severity.BREAKING
        assert "type changed" in breaking[0].description.lower()

    def test_type_widening_is_warning(self):
        old = [_ep(resp={"score": {"type": "integer"}})]
        new = [_ep(resp={"score": {"type": "number"}})]
        breaking, non_breaking = diff_endpoints(old, new)
        assert breaking == []
        assert len(non_breaking) == 1
        assert non_breaking[0].severity == Severity.WARNING
        assert "widened" in non_breaking[0].description.lower()


class TestRequiredChanges:
    def test_optional_to_required_is_warning(self):
        old = [_ep(req={"name": {"type": "string", "required": False}})]
        new = [_ep(req={"name": {"type": "string", "required": True}})]
        _, non_breaking = diff_endpoints(old, new)
        warnings = [c for c in non_breaking if c.severity == Severity.WARNING]
        assert len(warnings) == 1
        assert "optional to required" in warnings[0].description.lower()


class TestMixedChanges:
    def test_complex_diff(self):
        old = [
            _ep(method="GET", path="/users",
                resp={"id": {"type": "integer"}, "name": {"type": "string"}}),
            _ep(method="DELETE", path="/users/{id}"),
        ]
        new = [
            _ep(method="GET", path="/users",
                resp={"id": {"type": "integer"}, "email": {"type": "string"}}),
            _ep(method="POST", path="/users",
                req={"name": {"type": "string", "required": True}}),
        ]
        breaking, non_breaking = diff_endpoints(old, new)

        # Breaking: DELETE removed + name removed from response
        assert len(breaking) >= 2

        # Non-breaking: POST added + email added to response
        assert len(non_breaking) >= 2
