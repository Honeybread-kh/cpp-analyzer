"""
Dependency graph builder using networkx.
Loads file-level #include edges from the DB and exposes graph query helpers
for visualizing inter-file dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

from ..db.repository import Repository


@dataclass
class FileNode:
    file_id: int
    path: str
    relative_path: str
    depth: int
    children: list["FileNode"] = field(default_factory=list)


class DependencyGraph:
    def __init__(self, repo: Repository, project_id: int):
        self.repo = repo
        self.project_id = project_id
        self._graph: "nx.DiGraph | None" = None

    # -- build ----------------------------------------------------------------

    def build(self, include_system: bool = False) -> None:
        """Resolve include file IDs, then build the directed graph.

        Nodes are file_id values; an edge from A to B means A includes B.
        """
        if not _NX_AVAILABLE:
            raise RuntimeError("networkx is not installed.  Run: pip install networkx")

        self.repo.resolve_include_file_ids(self.project_id)

        self._graph = nx.DiGraph()
        edges = self.repo.all_includes(self.project_id, include_system=include_system)
        for e in edges:
            self._graph.add_edge(e["file_id"], e["included_file_id"])

    def _ensure_built(self) -> None:
        if self._graph is None:
            self.build()

    @property
    def graph(self) -> "nx.DiGraph":
        self._ensure_built()
        return self._graph

    # -- queries --------------------------------------------------------------

    def includes_of(self, file_id: int, depth: int = 1) -> list[int]:
        """Files that *file_id* includes (successors), up to *depth* hops."""
        g = self.graph
        if file_id not in g:
            return []
        if depth == 1:
            return list(g.successors(file_id))
        if depth < 0:
            return list(nx.descendants(g, file_id))
        seen: set[int] = set()
        frontier = {file_id}
        for _ in range(depth):
            next_frontier: set[int] = set()
            for node in frontier:
                for succ in g.successors(node):
                    if succ not in seen:
                        seen.add(succ)
                        next_frontier.add(succ)
            frontier = next_frontier
        return list(seen)

    def included_by(self, file_id: int, depth: int = 1) -> list[int]:
        """Files that include *file_id* (predecessors), up to *depth* hops."""
        g = self.graph
        if file_id not in g:
            return []
        if depth == 1:
            return list(g.predecessors(file_id))
        if depth < 0:
            return list(nx.ancestors(g, file_id))
        seen: set[int] = set()
        frontier = {file_id}
        for _ in range(depth):
            next_frontier: set[int] = set()
            for node in frontier:
                for pred in g.predecessors(node):
                    if pred not in seen:
                        seen.add(pred)
                        next_frontier.add(pred)
            frontier = next_frontier
        return list(seen)

    def circular_dependencies(self) -> list[list[int]]:
        """Detect circular include dependencies using nx.simple_cycles."""
        g = self.graph
        return list(nx.simple_cycles(g))

    def top_included(self, n: int = 15) -> list[tuple[int, int]]:
        """Files most frequently included by others (highest in-degree)."""
        g = self.graph
        return sorted(g.in_degree(), key=lambda x: x[1], reverse=True)[:n]

    def top_includers(self, n: int = 15) -> list[tuple[int, int]]:
        """Files that include the most other files (highest out-degree)."""
        g = self.graph
        return sorted(g.out_degree(), key=lambda x: x[1], reverse=True)[:n]

    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    # -- tree builder ---------------------------------------------------------

    def build_tree(
        self,
        file_id: int,
        direction: str = "includes",
        max_depth: int = 4,
    ) -> FileNode | None:
        """Build a FileNode tree rooted at *file_id*.

        direction='includes'    -> what this file includes (successors)
        direction='included-by' -> who includes this file (predecessors)
        """
        g = self.graph
        if file_id not in g:
            return None
        return self._build_tree(file_id, direction, max_depth, 0, set())

    def _build_tree(
        self,
        file_id: int,
        direction: str,
        max_depth: int,
        current_depth: int,
        visited: set[int],
    ) -> FileNode:
        node = self._make_file_node(file_id, current_depth)
        if current_depth >= max_depth or file_id in visited:
            return node
        visited = visited | {file_id}
        neighbors = (
            list(self.graph.successors(file_id))
            if direction == "includes"
            else list(self.graph.predecessors(file_id))
        )
        for n_id in neighbors[:15]:  # cap breadth
            child = self._build_tree(n_id, direction, max_depth, current_depth + 1, visited)
            node.children.append(child)
        return node

    def _make_file_node(self, file_id: int, depth: int) -> FileNode:
        row = self.repo.get_file(file_id)
        if row:
            return FileNode(
                file_id=file_id,
                path=row["path"],
                relative_path=row["relative_path"],
                depth=depth,
            )
        return FileNode(
            file_id=file_id,
            path=f"<id:{file_id}>",
            relative_path=f"<id:{file_id}>",
            depth=depth,
        )
