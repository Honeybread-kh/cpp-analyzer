"""
Indexer: walks a directory tree, parses each C++ file, and stores results in the DB.
Supports incremental re-indexing (skips unchanged files by file hash).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from ..core.ast_parser import ClangParser, ParseResult
from ..db.repository import Repository

C_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c", ".C", ".h", ".hpp", ".hxx", ".hh"}


class Indexer:
    def __init__(
        self,
        repo: Repository,
        project_id: int,
        root_paths: str | Path | list[str] | list[Path],
        extra_clang_args: list[str] | None = None,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ):
        self.repo = repo
        self.project_id = project_id

        # Normalise to a list of resolved Paths
        if isinstance(root_paths, (str, Path)):
            self.roots: list[Path] = [Path(root_paths).resolve()]
        else:
            self.roots = [Path(p).resolve() for p in root_paths]

        # Keep legacy attribute for backwards compatibility
        self.root = self.roots[0]

        self.parser = ClangParser(extra_clang_args)
        self.progress_cb = progress_cb or (lambda *_: None)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, force: bool = False) -> IndexStats:
        stats = IndexStats()
        files = self._collect_files()
        total = len(files)

        # Bulk-load all file hashes to avoid per-file DB queries
        hash_cache = self.repo.get_all_file_hashes(self.project_id) if not force else {}

        # Disable FK checks during indexing to avoid INSERT OR REPLACE
        # cascading deletes when USR collisions occur across files
        self.repo.set_foreign_keys(False)

        for i, path in enumerate(files, 1):
            self.progress_cb(str(path), i, total)
            owning_root = self._owning_root(path)
            rel = str(path.relative_to(owning_root))

            # incremental: skip if hash unchanged (check before expensive parse)
            if not force:
                file_hash = self.parser.compute_file_hash(path)
                if hash_cache.get(rel) == file_hash:
                    stats.skipped += 1
                    continue

            result = self.parser.parse_file(path)

            if result.used_fallback:
                stats.fallback += 1

            # Batch: single transaction per file for all DB writes
            with self.repo.transaction() as conn:
                file_id = self.repo.upsert_file(
                    project_id   = self.project_id,
                    path         = str(path),
                    relative_path= rel,
                    file_hash    = result.file_hash,
                    last_modified= path.stat().st_mtime,
                    line_count   = result.line_count,
                    _conn        = conn,
                )

                # clear stale data for this file
                self.repo.delete_file_symbols(file_id, _conn=conn)

                # --- symbols
                usr_to_id: dict[str, int] = {}
                for sym in result.symbols:
                    parent_db_id = usr_to_id.get(sym.parent_usr) if sym.parent_usr else None
                    sym_id = self.repo.insert_symbol(
                        file_id        = file_id,
                        name           = sym.name,
                        qualified_name = sym.qualified_name,
                        kind           = sym.kind,
                        signature      = sym.signature,
                        line_start     = sym.line_start,
                        line_end       = sym.line_end,
                        col_start      = sym.col_start,
                        is_definition  = sym.is_definition,
                        is_declaration = sym.is_declaration,
                        parent_id      = parent_db_id,
                        namespace_path = sym.namespace_path,
                        visibility     = sym.visibility,
                        return_type    = sym.return_type,
                        usr            = sym.usr,
                        template_params= sym.template_params,
                        _conn          = conn,
                    )
                    usr_to_id[sym.usr] = sym_id

                # --- calls
                for call in result.calls:
                    caller_id = usr_to_id.get(call.caller_usr)
                    if caller_id is None:
                        caller_id = self.repo.resolve_symbol_id(call.caller_usr)
                    if caller_id is None:
                        continue
                    callee_id = None
                    if call.callee_usr:
                        callee_id = usr_to_id.get(call.callee_usr) or \
                                    self.repo.resolve_symbol_id(call.callee_usr)
                    self.repo.insert_call(
                        caller_id    = caller_id,
                        callee_name  = call.callee_name,
                        callee_id    = callee_id,
                        call_file_id = file_id,
                        call_line    = call.line,
                        call_col     = call.col,
                        code_snippet = call.code_snippet,
                        call_type    = call.call_type,
                        _conn        = conn,
                    )

                # --- includes
                for inc in result.includes:
                    self.repo.insert_include(
                        file_id          = file_id,
                        included_file_id = None,
                        included_path    = inc.included_path,
                        line             = inc.line,
                        is_system        = inc.is_system,
                        _conn            = conn,
                    )

                # --- class inheritance
                for inh in result.inherits:
                    class_db_id = usr_to_id.get(inh.class_usr)
                    if class_db_id is None:
                        class_db_id = self.repo.resolve_symbol_id(inh.class_usr)
                    if class_db_id is None:
                        continue
                    base_db_id = None
                    if inh.base_usr:
                        base_db_id = usr_to_id.get(inh.base_usr) or \
                                     self.repo.resolve_symbol_id(inh.base_usr)
                    self.repo.insert_inheritance(
                        class_symbol_id = class_db_id,
                        base_class_name = inh.base_name,
                        base_class_usr  = inh.base_usr,
                        base_class_id   = base_db_id,
                        access          = inh.access,
                        is_virtual      = inh.is_virtual,
                        _conn           = conn,
                    )

            stats.indexed += 1
            stats.symbols  += len(result.symbols)
            stats.calls    += len(result.calls)
            if result.errors:
                stats.parse_errors.append((rel, result.errors))

        self.repo.set_foreign_keys(True)
        self.repo.touch_project(self.project_id)
        return stats

    # ── helpers ───────────────────────────────────────────────────────────────

    def _collect_files(self) -> list[Path]:
        out: list[Path] = []
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                # skip hidden dirs and common build/vendor dirs
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".")
                    and d not in {"build", "cmake-build-debug", "cmake-build-release",
                                  "node_modules", "_deps", "third_party", "vendor"}
                ]
                for fn in filenames:
                    if Path(fn).suffix.lower() in C_EXTENSIONS:
                        out.append(Path(dirpath) / fn)
        return sorted(out)

    def _owning_root(self, path: Path) -> Path:
        """Return the root directory that contains *path*.

        When multiple roots could match (nested directories), the longest
        (most specific) root wins.
        """
        resolved = path.resolve()
        best: Path | None = None
        for root in self.roots:
            try:
                resolved.relative_to(root)
                if best is None or len(root.parts) > len(best.parts):
                    best = root
            except ValueError:
                continue
        if best is None:
            # Fallback: should not happen if _collect_files works correctly
            return self.roots[0]
        return best


class IndexStats:
    def __init__(self):
        self.indexed      = 0
        self.skipped      = 0
        self.fallback     = 0
        self.symbols      = 0
        self.calls        = 0
        self.parse_errors: list[tuple[str, list[str]]] = []

    def __repr__(self):
        return (
            f"IndexStats(indexed={self.indexed}, skipped={self.skipped}, "
            f"fallback={self.fallback}, symbols={self.symbols}, calls={self.calls}, "
            f"errors={len(self.parse_errors)})"
        )
