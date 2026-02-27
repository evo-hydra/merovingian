"""Frozen dataclass models for Merovingian domain objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from merovingian.models.enums import (
    ChangeKind,
    ContractType,
    FeedbackOutcome,
    Severity,
    TargetType,
)


def _now() -> datetime:
    """UTC now factory for dataclass defaults."""
    return datetime.now(timezone.utc)


def _uuid_hex() -> str:
    """Generate a UUID4 hex string."""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class RepoInfo:
    """A registered repository."""

    name: str
    path: str
    contract_type: ContractType | None = None
    registered_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class SchemaField:
    """A single field within a request or response schema."""

    name: str
    field_type: str
    required: bool = True
    default: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Endpoint:
    """An API endpoint or schema contract exposed by a repository."""

    repo_name: str
    method: str
    path: str
    summary: str | None = None
    request_schema: str | None = None  # JSON dict
    response_schema: str | None = None  # JSON dict


@dataclass(frozen=True, slots=True)
class Consumer:
    """A consumer relationship between two repositories."""

    consumer_repo: str
    producer_repo: str
    endpoint_method: str
    endpoint_path: str
    registered_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class ContractVersion:
    """A snapshot of a repository's contract at a point in time."""

    repo_name: str
    version_id: str = field(default_factory=_uuid_hex)
    spec_hash: str = ""
    endpoints: tuple[Endpoint, ...] = ()
    captured_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class ContractChange:
    """A detected change in a contract, with severity indicating impact level."""

    repo_name: str
    endpoint_method: str
    endpoint_path: str
    change_kind: ChangeKind
    severity: Severity
    description: str
    affected_consumers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImpactReport:
    """Full impact assessment for a repository's contract changes."""

    repo_name: str
    report_id: str = field(default_factory=_uuid_hex)
    breaking_changes: tuple[ContractChange, ...] = ()
    non_breaking_changes: tuple[ContractChange, ...] = ()
    consumer_count: int = 0
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class Feedback:
    """User feedback on a report or change."""

    target_id: str
    target_type: TargetType = TargetType.REPORT
    outcome: FeedbackOutcome = FeedbackOutcome.ACCEPTED
    context: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Audit log entry for an MCP tool invocation."""

    tool_name: str
    parameters: str  # JSON string
    result_summary: str
    created_at: datetime = field(default_factory=_now)
