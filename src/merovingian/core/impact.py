"""Impact assessment orchestrator."""

from __future__ import annotations

from merovingian.config import ScannerConfig
from merovingian.core.differ import diff_endpoints
from merovingian.core.registry import get_affected_consumers
from merovingian.core.scanner import compute_spec_hash, scan_repo
from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import (
    BreakingChange,
    ContractVersion,
    ImpactReport,
    RepoInfo,
)


def assess_impact(
    store: MerovingianStore,
    repo_name: str,
    config: ScannerConfig,
) -> ImpactReport:
    """Full impact assessment: scan, diff, find affected consumers, save report.

    1. Load current endpoints from store
    2. Re-scan repo to get latest endpoints
    3. Diff old vs new
    4. Look up affected consumers
    5. Attach consumer names to each BreakingChange
    6. Save new contract version + impact report
    7. Return report
    """
    repo = store.get_repo(repo_name)
    if repo is None:
        raise ValueError(f"Repository '{repo_name}' not registered")

    # 1. Load current endpoints
    old_endpoints = store.get_endpoints(repo_name)

    # 2. Re-scan
    new_endpoints = scan_repo(repo, config)

    # 3. Diff
    breaking, non_breaking = diff_endpoints(old_endpoints, new_endpoints)

    # 4. Affected consumers
    affected_map = get_affected_consumers(store, breaking)

    # 5. Attach consumer names
    breaking_with_consumers = tuple(
        BreakingChange(
            repo_name=bc.repo_name,
            endpoint_method=bc.endpoint_method,
            endpoint_path=bc.endpoint_path,
            change_kind=bc.change_kind,
            severity=bc.severity,
            description=bc.description,
            affected_consumers=tuple(affected_map.get(bc, ())),
        )
        for bc in breaking
    )

    # Collect unique consumer count
    all_consumers: set[str] = set()
    for consumers in affected_map.values():
        all_consumers.update(consumers)

    # 6. Save new contract version
    spec_hash = compute_spec_hash(new_endpoints)
    version = ContractVersion(
        repo_name=repo_name,
        spec_hash=spec_hash,
        endpoints=tuple(new_endpoints),
    )
    store.save_version(version)

    # Update stored endpoints
    store.delete_endpoints(repo_name)
    store.save_endpoints(new_endpoints)

    # Save report
    report = ImpactReport(
        repo_name=repo_name,
        breaking_changes=breaking_with_consumers,
        non_breaking_changes=tuple(non_breaking),
        consumer_count=len(all_consumers),
    )
    store.save_report(report)

    return report


def check_breaking(
    store: MerovingianStore,
    repo_name: str,
    config: ScannerConfig,
) -> list[BreakingChange]:
    """Lightweight breaking change check — scan + diff, no persistence."""
    repo = store.get_repo(repo_name)
    if repo is None:
        raise ValueError(f"Repository '{repo_name}' not registered")

    old_endpoints = store.get_endpoints(repo_name)
    new_endpoints = scan_repo(repo, config)
    breaking, _ = diff_endpoints(old_endpoints, new_endpoints)

    # Attach affected consumers
    affected_map = get_affected_consumers(store, breaking)
    return [
        BreakingChange(
            repo_name=bc.repo_name,
            endpoint_method=bc.endpoint_method,
            endpoint_path=bc.endpoint_path,
            change_kind=bc.change_kind,
            severity=bc.severity,
            description=bc.description,
            affected_consumers=tuple(affected_map.get(bc, ())),
        )
        for bc in breaking
    ]
