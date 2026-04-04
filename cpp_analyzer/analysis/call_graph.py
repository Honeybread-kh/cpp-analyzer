"""
Call graph builder using networkx.
Loads caller→callee edges from the DB and exposes graph query helpers.
"""

from __future__ import annotations

from typing import Generator

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

from ..db.repository import Repository


class CallGraph:
    def __init__(self, repo: Repository, project_id: int):
        self.repo = repo
        self.project_id = project_id
        self._graph: "nx.DiGraph | None" = None

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        if not _NX_AVAILABLE:
            raise RuntimeError("networkx is not installed.  Run: pip install networkx")

        self._graph = nx.DiGraph()
        edges = self.repo.all_calls(self.project_id)
        for e in edges:
            self._graph.add_edge(e["caller_id"], e["callee_id"])

    def _ensure_built(self) -> None:
        if self._graph is None:
            self.build()

    @property
    def graph(self) -> "nx.DiGraph":
        self._ensure_built()
        return self._graph

    # ── queries ───────────────────────────────────────────────────────────────

    def callers_of(self, symbol_id: int, depth: int = 1) -> list[int]:
        """Direct or transitive callers up to *depth* hops.  -1 = unlimited."""
        g = self.graph
        if symbol_id not in g:
            return []
        if depth == 1:
            return list(g.predecessors(symbol_id))
        if depth < 0:
            return list(nx.ancestors(g, symbol_id))
        # BFS up to depth hops
        seen: set[int] = set()
        frontier = {symbol_id}
        for _ in range(depth):
            next_frontier: set[int] = set()
            for node in frontier:
                for pred in g.predecessors(node):
                    if pred not in seen:
                        seen.add(pred)
                        next_frontier.add(pred)
            frontier = next_frontier
        return list(seen)

    def callees_of(self, symbol_id: int, depth: int = 1) -> list[int]:
        """Direct or transitive callees."""
        g = self.graph
        if symbol_id not in g:
            return []
        if depth == 1:
            return list(g.successors(symbol_id))
        if depth < 0:
            return list(nx.descendants(g, symbol_id))
        seen: set[int] = set()
        frontier = {symbol_id}
        for _ in range(depth):
            next_frontier: set[int] = set()
            for node in frontier:
                for succ in g.successors(node):
                    if succ not in seen:
                        seen.add(succ)
                        next_frontier.add(succ)
            frontier = next_frontier
        return list(seen)

    def all_paths(
        self, source_id: int, target_id: int, max_paths: int = 20
    ) -> list[list[int]]:
        """All simple paths from source to target (capped at max_paths)."""
        g = self.graph
        if source_id not in g or target_id not in g:
            return []
        paths = []
        try:
            for p in nx.all_simple_paths(g, source_id, target_id, cutoff=15):
                paths.append(p)
                if len(paths) >= max_paths:
                    break
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
        return paths

    def shortest_path(self, source_id: int, target_id: int) -> list[int]:
        g = self.graph
        try:
            return nx.shortest_path(g, source_id, target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def reachable_from(self, symbol_id: int) -> set[int]:
        """All functions reachable from symbol_id (its entire sub-tree)."""
        g = self.graph
        if symbol_id not in g:
            return set()
        return nx.descendants(g, symbol_id)

    def can_reach(self, source_id: int, target_id: int) -> bool:
        g = self.graph
        if source_id not in g or target_id not in g:
            return False
        return nx.has_path(g, source_id, target_id)

    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def top_callers(self, n: int = 10) -> list[tuple[int, int]]:
        """Return (symbol_id, in_degree) sorted by most-called."""
        g = self.graph
        return sorted(g.in_degree(), key=lambda x: x[1], reverse=True)[:n]

    def top_callees(self, n: int = 10) -> list[tuple[int, int]]:
        """Return (symbol_id, out_degree) sorted by most outgoing calls."""
        g = self.graph
        return sorted(g.out_degree(), key=lambda x: x[1], reverse=True)[:n]
