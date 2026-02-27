"""Consumer registry and dependency graph management."""

from __future__ import annotations

from merovingian.core.store import MerovingianStore
from merovingian.models.contracts import BreakingChange, Consumer


def register_consumer(
    store: MerovingianStore,
    consumer_repo: str,
    producer_repo: str,
    method: str,
    path: str,
) -> Consumer:
    """Register a consumer relationship, validating the endpoint exists."""
    endpoints = store.get_endpoints(producer_repo)
    matching = [ep for ep in endpoints if ep.method == method and ep.path == path]
    if not matching:
        raise ValueError(
            f"Endpoint {method} {path} not found in repo '{producer_repo}'. "
            f"Run 'merovingian scan {producer_repo}' first."
        )

    consumer = Consumer(
        consumer_repo=consumer_repo,
        producer_repo=producer_repo,
        endpoint_method=method,
        endpoint_path=path,
    )
    store.add_consumer(consumer)
    return consumer


def get_affected_consumers(
    store: MerovingianStore,
    breaking_changes: list[BreakingChange],
) -> dict[BreakingChange, list[str]]:
    """Map each breaking change to its list of affected consumer repo names."""
    result: dict[BreakingChange, list[str]] = {}

    for change in breaking_changes:
        consumers = store.get_consumers_of(
            change.repo_name, change.endpoint_method, change.endpoint_path,
        )
        consumer_names = [c.consumer_repo for c in consumers]

        # Also check repo-level consumers for removed endpoints
        if not consumer_names:
            repo_consumers = store.get_consumers_of_repo(change.repo_name)
            for c in repo_consumers:
                if c.endpoint_method == change.endpoint_method and c.endpoint_path == change.endpoint_path:
                    consumer_names.append(c.consumer_repo)

        result[change] = consumer_names

    return result


def build_dependency_graph(store: MerovingianStore) -> dict[str, dict[str, list[str]]]:
    """Build a dependency graph as an adjacency list.

    Returns: {repo: {"depends_on": [...], "depended_by": [...]}}
    """
    repos = store.list_repos()
    graph: dict[str, dict[str, list[str]]] = {
        repo.name: {"depends_on": [], "depended_by": []}
        for repo in repos
    }

    for repo in repos:
        consumers = store.get_consumers_of_repo(repo.name)
        depended_by_names: set[str] = set()
        for consumer in consumers:
            depended_by_names.add(consumer.consumer_repo)
            # Ensure consumer repo is in graph even if not registered
            if consumer.consumer_repo not in graph:
                graph[consumer.consumer_repo] = {"depends_on": [], "depended_by": []}
            if repo.name not in graph[consumer.consumer_repo]["depends_on"]:
                graph[consumer.consumer_repo]["depends_on"].append(repo.name)

        graph[repo.name]["depended_by"] = sorted(depended_by_names)

    return graph
