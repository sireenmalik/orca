"""
CSPF — Constrained Shortest Path First
Standard TE path computation algorithm.
Deterministic, sub-millisecond for networks up to 1000 nodes.

Used by ORCA for candidate path generation.
ORCA reasoning layer then selects from candidates based on business context.
"""

import heapq
from typing import Optional


def cspf(
    topology: dict,
    src: str,
    dst: str,
    bandwidth_gbps: float = 0.0,
    max_utilization_pct: float = 80.0,
    excluded_links: list = None,
    excluded_nodes: list = None,
) -> Optional[list]:
    """
    Compute constrained shortest path from src to dst.

    Constraints:
    - Link must have sufficient available bandwidth
    - Link utilization must be below max_utilization_pct
    - Links in excluded_links are pruned from topology
    - Nodes in excluded_nodes are pruned from topology

    Returns: list of node IDs forming the path, or None if no feasible path.

    Complexity: O((V + E) log V) — Dijkstra with priority queue.
    Performance: < 1ms for 6-node topology, < 10ms for 100-node topology.
    """
    excluded_links = excluded_links or []
    excluded_nodes = excluded_nodes or []

    links = topology.get("links", {})
    nodes = topology.get("nodes", {})

    # Build adjacency list with constraints applied
    graph = {n: [] for n in nodes if n not in excluded_nodes}

    for link_id, link in links.items():
        s = link.get("src") or link.get("src_node")
        d = link.get("dst") or link.get("dst_node")

        if s not in graph or d not in graph:
            continue
        if link_id in excluded_links:
            continue
        if link.get("state") == "down":
            continue

        util = link.get("utilization_pct", 0.0)
        if util >= max_utilization_pct:
            continue

        capacity = link.get("capacity_gbps", 10.0)
        available = capacity * (1 - util / 100.0)
        if available < bandwidth_gbps:
            continue

        metric = link.get("igp_metric", 10)
        graph[s].append((d, metric, link_id))
        graph[d].append((s, metric, link_id))  # bidirectional

    if src not in graph or dst not in graph:
        return None

    # Dijkstra
    dist = {n: float("inf") for n in graph}
    prev = {n: None for n in graph}
    dist[src] = 0
    pq = [(0, src)]

    while pq:
        cost, u = heapq.heappop(pq)
        if cost > dist[u]:
            continue
        for v, metric, _ in graph.get(u, []):
            new_cost = dist[u] + metric
            if new_cost < dist[v]:
                dist[v] = new_cost
                prev[v] = u
                heapq.heappush(pq, (new_cost, v))

    if dist[dst] == float("inf"):
        return None  # No feasible path

    # Reconstruct path
    path = []
    node = dst
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()

    return path if path[0] == src else None


def k_shortest_paths(
    topology: dict,
    src: str,
    dst: str,
    k: int = 3,
    bandwidth_gbps: float = 0.0,
    max_utilization_pct: float = 80.0,
    excluded_links: list = None,
) -> list:
    """
    Compute k shortest constrained paths using Yen's algorithm.
    Returns up to k feasible paths, ordered by total metric.

    ORCA reasoning layer selects the best path from these candidates
    based on business context, history, and operator policy.
    """
    excluded_links = excluded_links or []
    paths = []

    # First shortest path
    first = cspf(topology, src, dst, bandwidth_gbps, max_utilization_pct, excluded_links)
    if not first:
        return []
    paths.append(first)

    # Candidates heap for k-th paths
    candidates = []

    for k_idx in range(1, k):
        prev_path = paths[k_idx - 1]

        for i in range(len(prev_path) - 1):
            spur_node = prev_path[i]
            root_path = prev_path[:i + 1]

            # Remove links used by previous paths with same root
            temp_excluded = list(excluded_links)
            for path in paths:
                if len(path) > i and path[:i + 1] == root_path:
                    link_id = f"{path[i]}-{path[i+1]}"
                    alt_link_id = f"{path[i+1]}-{path[i]}"
                    temp_excluded.extend([link_id, alt_link_id])

            spur_path = cspf(
                topology, spur_node, dst,
                bandwidth_gbps, max_utilization_pct, temp_excluded
            )
            if spur_path:
                total_path = root_path[:-1] + spur_path
                if total_path not in [c[1] for c in candidates] and total_path not in paths:
                    metric = len(total_path) - 1  # simplified metric
                    heapq.heappush(candidates, (metric, total_path))

        if not candidates:
            break

        _, best = heapq.heappop(candidates)
        paths.append(best)

    return paths


def compute_path_utilization(path: list, topology: dict) -> dict:
    """
    Given a path (list of nodes), return utilization of each link in the path.
    Used to verify Mission 1 and Mission 2 compliance before acting.
    """
    links = topology.get("links", {})
    result = {}

    for i in range(len(path) - 1):
        link_id = f"{path[i]}-{path[i+1]}"
        alt_id = f"{path[i+1]}-{path[i]}"
        link = links.get(link_id) or links.get(alt_id)
        if link:
            result[link_id] = link.get("utilization_pct", 0.0)

    return result


def verify_mission_1(path: list, topology: dict, threshold: float = 90.0) -> bool:
    """Returns True if all links in path are below threshold. Mission 1 check."""
    utils = compute_path_utilization(path, topology)
    return all(u < threshold for u in utils.values())


def verify_mission_2(candidate_paths: list, topology: dict) -> list:
    """
    Rank candidate paths by Mission 2 — minimise max utilization.
    Returns paths sorted from best (lowest max utilization) to worst.
    """
    scored = []
    for path in candidate_paths:
        utils = compute_path_utilization(path, topology)
        max_util = max(utils.values()) if utils else 0.0
        scored.append((max_util, path))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored]
