"""Enumerations for Merovingian domain model."""

from __future__ import annotations

from enum import Enum


class ChangeKind(str, Enum):
    """Type of change detected in a contract diff."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"


class Severity(str, Enum):
    """Severity level of a detected change."""

    BREAKING = "breaking"
    WARNING = "warning"
    INFO = "info"


class ContractType(str, Enum):
    """Type of contract a repository exposes."""

    OPENAPI = "openapi"
    PYDANTIC = "pydantic"


class FeedbackOutcome(str, Enum):
    """Outcome of user feedback."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"


class TargetType(str, Enum):
    """Type of target a feedback entry refers to."""

    REPORT = "report"
    CHANGE = "change"
