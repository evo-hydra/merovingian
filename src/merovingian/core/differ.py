"""Spec diff engine — breaking vs non-breaking change classification."""

from __future__ import annotations

import json

from merovingian.models.contracts import ContractChange, Endpoint
from merovingian.models.enums import ChangeKind, Severity


def diff_endpoints(
    old: list[Endpoint], new: list[Endpoint]
) -> tuple[list[ContractChange], list[ContractChange]]:
    """Compare two sets of endpoints and classify changes.

    Returns (breaking_changes, non_breaking_changes).
    """
    old_map = {(ep.method, ep.path): ep for ep in old}
    new_map = {(ep.method, ep.path): ep for ep in new}

    breaking: list[ContractChange] = []
    non_breaking: list[ContractChange] = []

    # Removed endpoints (breaking)
    for key, ep in old_map.items():
        if key not in new_map:
            breaking.append(ContractChange(
                repo_name=ep.repo_name,
                endpoint_method=ep.method,
                endpoint_path=ep.path,
                change_kind=ChangeKind.REMOVED,
                severity=Severity.BREAKING,
                description=f"Endpoint {ep.method} {ep.path} removed",
            ))

    # Added endpoints (non-breaking)
    for key, ep in new_map.items():
        if key not in old_map:
            non_breaking.append(ContractChange(
                repo_name=ep.repo_name,
                endpoint_method=ep.method,
                endpoint_path=ep.path,
                change_kind=ChangeKind.ADDED,
                severity=Severity.INFO,
                description=f"Endpoint {ep.method} {ep.path} added",
            ))

    # Modified endpoints — diff schemas
    for key in old_map:
        if key not in new_map:
            continue
        old_ep = old_map[key]
        new_ep = new_map[key]

        # Diff request schema
        old_req = _parse_schema(old_ep.request_schema)
        new_req = _parse_schema(new_ep.request_schema)
        if old_req or new_req:
            b, nb = _diff_schema(
                old_req, new_req, direction="request",
                repo_name=old_ep.repo_name, method=old_ep.method, path=old_ep.path,
            )
            breaking.extend(b)
            non_breaking.extend(nb)

        # Diff response schema
        old_resp = _parse_schema(old_ep.response_schema)
        new_resp = _parse_schema(new_ep.response_schema)
        if old_resp or new_resp:
            b, nb = _diff_schema(
                old_resp, new_resp, direction="response",
                repo_name=old_ep.repo_name, method=old_ep.method, path=old_ep.path,
            )
            breaking.extend(b)
            non_breaking.extend(nb)

        # Summary change (non-breaking)
        if old_ep.summary != new_ep.summary and new_ep.summary:
            non_breaking.append(ContractChange(
                repo_name=old_ep.repo_name,
                endpoint_method=old_ep.method,
                endpoint_path=old_ep.path,
                change_kind=ChangeKind.MODIFIED,
                severity=Severity.INFO,
                description=f"Summary changed for {old_ep.method} {old_ep.path}",
            ))

    return breaking, non_breaking


def _parse_schema(schema_json: str | None) -> dict:
    """Parse a JSON schema string to a dict."""
    if not schema_json:
        return {}
    try:
        return json.loads(schema_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _diff_schema(
    old_schema: dict,
    new_schema: dict,
    direction: str,
    repo_name: str,
    method: str,
    path: str,
) -> tuple[list[ContractChange], list[ContractChange]]:
    """Diff two schema field dicts with direction-aware breaking logic.

    direction="request": adding required field = breaking (consumers don't send it)
    direction="response": removing field = breaking (consumers may depend on it)
    """
    breaking: list[ContractChange] = []
    non_breaking: list[ContractChange] = []

    old_fields = set(old_schema.keys())
    new_fields = set(new_schema.keys())

    # Fields removed
    for field_name in old_fields - new_fields:
        if direction == "response":
            breaking.append(ContractChange(
                repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                change_kind=ChangeKind.REMOVED, severity=Severity.BREAKING,
                description=f"Response field '{field_name}' removed from {method} {path}",
            ))
        else:
            non_breaking.append(ContractChange(
                repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                change_kind=ChangeKind.REMOVED, severity=Severity.INFO,
                description=f"Request field '{field_name}' removed from {method} {path}",
            ))

    # Fields added
    for field_name in new_fields - old_fields:
        new_field = new_schema[field_name]
        is_required = new_field.get("required", False)

        if direction == "request" and is_required:
            breaking.append(ContractChange(
                repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                change_kind=ChangeKind.ADDED, severity=Severity.BREAKING,
                description=f"Required request field '{field_name}' added to {method} {path}",
            ))
        elif direction == "response":
            non_breaking.append(ContractChange(
                repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                change_kind=ChangeKind.ADDED, severity=Severity.INFO,
                description=f"Response field '{field_name}' added to {method} {path}",
            ))
        else:
            non_breaking.append(ContractChange(
                repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                change_kind=ChangeKind.ADDED, severity=Severity.INFO,
                description=f"Optional request field '{field_name}' added to {method} {path}",
            ))

    # Fields modified (type changes, required changes)
    for field_name in old_fields & new_fields:
        old_field = old_schema[field_name]
        new_field = new_schema[field_name]

        old_type = old_field.get("type", "")
        new_type = new_field.get("type", "")

        # Type changed
        if old_type != new_type:
            if _is_type_widening(old_type, new_type):
                non_breaking.append(ContractChange(
                    repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                    change_kind=ChangeKind.MODIFIED, severity=Severity.WARNING,
                    description=(
                        f"Field '{field_name}' type widened from "
                        f"'{old_type}' to '{new_type}' in {direction} of {method} {path}"
                    ),
                ))
            else:
                breaking.append(ContractChange(
                    repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                    change_kind=ChangeKind.MODIFIED, severity=Severity.BREAKING,
                    description=(
                        f"Field '{field_name}' type changed from "
                        f"'{old_type}' to '{new_type}' in {direction} of {method} {path}"
                    ),
                ))

        # Required changed
        old_required = old_field.get("required", False)
        new_required = new_field.get("required", False)
        if old_required != new_required:
            if not old_required and new_required:
                # Optional → required
                if direction == "request":
                    # Consumers may not be sending this field — breaking
                    breaking.append(ContractChange(
                        repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                        change_kind=ChangeKind.MODIFIED, severity=Severity.BREAKING,
                        description=(
                            f"Field '{field_name}' changed from optional to required "
                            f"in {direction} of {method} {path}"
                        ),
                    ))
                else:
                    # Response field becoming required is safe for consumers
                    non_breaking.append(ContractChange(
                        repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                        change_kind=ChangeKind.MODIFIED, severity=Severity.INFO,
                        description=(
                            f"Field '{field_name}' changed from optional to required "
                            f"in {direction} of {method} {path}"
                        ),
                    ))
            else:
                # Required → optional
                if direction == "response":
                    # Consumers relying on guaranteed presence — warning
                    non_breaking.append(ContractChange(
                        repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                        change_kind=ChangeKind.MODIFIED, severity=Severity.WARNING,
                        description=(
                            f"Field '{field_name}' changed from required to optional "
                            f"in {direction} of {method} {path}"
                        ),
                    ))
                else:
                    # Request field relaxed — safe for consumers
                    non_breaking.append(ContractChange(
                        repo_name=repo_name, endpoint_method=method, endpoint_path=path,
                        change_kind=ChangeKind.MODIFIED, severity=Severity.INFO,
                        description=(
                            f"Field '{field_name}' changed from required to optional "
                            f"in {direction} of {method} {path}"
                        ),
                    ))

    return breaking, non_breaking


def _is_type_widening(old_type: str, new_type: str) -> bool:
    """Check if a type change is a widening (safe broadening)."""
    widening_pairs = {
        ("integer", "number"),
        ("int", "float"),
        ("int", "number"),
    }
    return (old_type, new_type) in widening_pairs
