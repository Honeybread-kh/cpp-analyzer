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
        root_path: str | Path,
        extra_clang_args: list[str] | None = None,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ):
        self.repo = repo
        self.project_id = project_id
        self.root = Path(root_path).resolve()
        self.parser = ClangParser(extra_clang_args)
        self.progress_cb = progress_cb or (lambda *_: None)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, force: bool = False) -> IndexStats:
        stats = IndexStats()
        files = self._collect_files()
        total = len(files)

        for i, path in enumerate(files, 1):
            self.progress_cb(str(path), i, total)
            rel = str(path.relative_to(self.root))

            # incremental: skip if hash unchanged
            if not force:
                result = self.parser.parse_file(path)
                stored_hash = self.repo.get_file_hash(self.project_id, rel)
                if stored_hash == result.file_hash:
                    stats.skipped += 1
                    continue
            else:
                result = self.parser.parse_file(path)

            if result.used_fallback:
                stats.fallback += 1

            file_id = self.repo.upsert_file(
                project_id   = self.project_id,
                path         = str(path),
                relative_path= rel,
                file_hash    = result.file_hash,
                last_modified= path.stat().st_mtime,
                line_count   = result.line_count,
            )

            # clear stale data for this file
            self.repo.delete_file_symbols(file_id)

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
                )

            # --- includes
            for inc in result.includes:
                self.repo.insert_include(
                    file_id          = file_id,
                    included_file_id = None,   # resolved in a second pass if needed
                    included_path    = inc.included_path,
                    line             = inc.line,
                    is_system        = inc.is_system,
                )

            stats.indexed += 1
            stats.symbols  += len(result.symbols)
            stats.calls    += len(result.calls)
            if result.errors:
                stats.parse_errors.append((rel, result.errors))

        self.repo.touch_project(self.project_id)
        return stats

    # ── helpers ───────────────────────────────────────────────────────────────

    def _collect_files(self) -> list[Path]:
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
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
