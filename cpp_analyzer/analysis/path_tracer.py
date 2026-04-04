"""
Path Tracer: answers questions like
  "Which functions are (transitively) affected by config key FOO?"
  "What is the call chain from function A to function B?"
  "Show me the full call tree rooted at function X."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..db.repository import Repository
from .call_graph import CallGraph


@dataclass
class PathNode:
    symbol_id: int
    qualified_name: str
    file: str
    line: int
    kind: str
    depth: int
    children: list["PathNode"] = field(default_factory=list)


@dataclass
class TraceResult:
    config_key: str
    source_nodes: list[PathNode]          # functions that directly read the config
    affected_functions: list[PathNode]    # all transitively affected functions
    call_chains: list[list[PathNode]]     # concrete call chains (source → leaf)
    stats: dict = field(default_factory=dict)


class PathTracer:
    def __init__(self, repo: Repository, cg: CallGraph, project_id: int):
        self.repo = repo
        self.cg = cg
        self.project_id = project_id

    # ── main API ──────────────────────────────────────────────────────────────

    def trace_config(
        self, config_key: str, max_depth: int = 6, max_chains: int = 30
    ) -> TraceResult:
        """Trace all code paths that are influenced by *config_key*."""
        # 1. Find functions that directly use the config key
        usages = self.repo.get_config_usages(self.project_id, config_key)
        direct_sym_ids: set[int] = set()
        for u in usages:
            if u["symbol_id"]:
                direct_sym_ids.add(u["symbol_id"])

        source_nodes = [self._make_node(sid, 0) for sid in direct_sym_ids if sid]

        # 2. For each source function, expand call tree downwards
        affected_ids: set[int] = set()
        for sid in direct_sym_ids:
            reachable = self.cg.callees_of(sid, depth=max_depth)
            affected_ids.update(reachable)
        affected_ids.update(direct_sym_ids)

        affected_nodes = [self._make_node(sid, 0) for sid in affected_ids]

        # 3. Build concrete call chains (source → max_depth deep)
        chains: list[list[PathNode]] = []
        for sid in direct_sym_ids:
            self._expand_chains(sid, [self._make_node(sid, 0)], chains, max_depth, max_chains)

        return TraceResult(
            config_key        = config_key,
            source_nodes      = source_nodes,
            affected_functions= affected_nodes,
            call_chains       = chains,
            stats={
                "direct_functions"   : len(direct_sym_ids),
                "affected_functions" : len(affected_ids),
                "call_chains"        : len(chains),
            },
        )

    def trace_path(
        self, source_name: str, target_name: str, max_paths: int = 10
    ) -> list[list[PathNode]]:
        """Find all call paths between two function names."""
        sources = self._find_by_name(source_name)
        targets = self._find_by_name(target_name)
        results: list[list[PathNode]] = []
        for src_id in sources:
            for tgt_id in targets:
                raw_paths = self.cg.all_paths(src_id, tgt_id, max_paths=max_paths)
                for p in raw_paths:
                    results.append([self._make_node(sid, depth) for depth, sid in enumerate(p)])
                if len(results) >= max_paths:
                    break
            if len(results) >= max_paths:
                break
        return results

    def call_tree(
        self, symbol_name: str, direction: str = "down", max_depth: int = 4
    ) -> PathNode | None:
        """
        Build a call tree rooted at *symbol_name*.
        direction='down'  → callee tree (what does this function call?)
        direction='up'    → caller tree (who calls this function?)
        """
        ids = self._find_by_name(symbol_name)
        if not ids:
            return None
        root_id = ids[0]
        return self._build_tree(root_id, direction, max_depth, 0, set())

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_node(self, symbol_id: int, depth: int) -> PathNode:
        row = self.repo.get_symbol(symbol_id)
        if row:
            return PathNode(
                symbol_id     = symbol_id,
                qualified_name= row["qualified_name"] or row["name"],
                file          = row["relative_path"],
                line          = row["line_start"] or 0,
                kind          = row["kind"],
                depth         = depth,
            )
        return PathNode(
            symbol_id=symbol_id, qualified_name=f"<id:{symbol_id}>",
            file="?", line=0, kind="?", depth=depth,
        )

    def _find_by_name(self, name: str) -> list[int]:
        rows = self.repo.search_symbols(name, project_id=self.project_id, limit=5)
        # prefer exact matches
        exact = [r["id"] for r in rows if r["name"] == name or r["qualified_name"] == name]
        if exact:
            return exact
        return [r["id"] for r in rows]

    def _expand_chains(
        self,
        current: int,
        chain: list[PathNode],
        out: list[list[PathNode]],
        max_depth: int,
        max_chains: int,
    ) -> None:
        if len(out) >= max_chains:
            return
        if len(chain) > max_depth:
            out.append(list(chain))
            return
        callees = self.cg.callees_of(current, depth=1)
        if not callees:
            out.append(list(chain))
            return
        for c_id in callees[:5]:   # cap fan-out per node
            node = self._make_node(c_id, len(chain))
            chain.append(node)
            self._expand_chains(c_id, chain, out, max_depth, max_chains)
            chain.pop()

    def _build_tree(
        self,
        symbol_id: int,
        direction: str,
        max_depth: int,
        current_depth: int,
        visited: set[int],
    ) -> PathNode:
        node = self._make_node(symbol_id, current_depth)
        if current_depth >= max_depth or symbol_id in visited:
            return node
        visited = visited | {symbol_id}
        neighbors = (
            self.cg.callees_of(symbol_id, depth=1)
            if direction == "down"
            else self.cg.callers_of(symbol_id, depth=1)
        )
        for n_id in neighbors[:8]:   # cap breadth
            child = self._build_tree(n_id, direction, max_depth, current_depth + 1, visited)
            node.children.append(child)
        return node
