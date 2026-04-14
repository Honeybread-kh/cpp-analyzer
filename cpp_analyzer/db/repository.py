"""
Database access layer.  All SQL lives here; the rest of the code sees Python objects.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schema import DDL, SCHEMA_VERSION


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._apply_schema()

    def set_foreign_keys(self, enabled: bool) -> None:
        """Enable or disable foreign key enforcement on the current connection.

        PRAGMA foreign_keys can only be changed outside of a transaction,
        so we commit any pending transaction first.
        """
        self._conn.commit()
        self._conn.execute(f"PRAGMA foreign_keys = {'ON' if enabled else 'OFF'}")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _apply_schema(self) -> None:
        self._conn.executescript(DDL)
        cur = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        )
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_meta VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        else:
            old_version = int(row["value"])
            if old_version < SCHEMA_VERSION:
                if old_version < 5:
                    self._migrate_to_v5()
                if old_version < 6:
                    self._migrate_to_v6()
                self._conn.execute(
                    "UPDATE schema_meta SET value=? WHERE key='version'",
                    (str(SCHEMA_VERSION),),
                )
                self._conn.commit()

    def _migrate_to_v5(self) -> None:
        """Migrate projects.root_path from single path string to JSON array.

        Also drops the UNIQUE constraint on root_path (handled by DDL change)
        and adds UNIQUE on name instead.
        """
        rows = self._conn.execute("SELECT id, root_path FROM projects").fetchall()
        for r in rows:
            rp = r["root_path"]
            # If already a JSON array, skip
            if rp.startswith("["):
                continue
            self._conn.execute(
                "UPDATE projects SET root_path=? WHERE id=?",
                (json.dumps([rp]), r["id"]),
            )
        self._conn.commit()

    def _migrate_to_v6(self) -> None:
        """Add call_args and dataflow_paths tables (v5 -> v6)."""
        # Tables are created by DDL (IF NOT EXISTS), just need to ensure they exist
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS call_args (
                id             INTEGER PRIMARY KEY,
                call_id        INTEGER NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
                arg_index      INTEGER NOT NULL,
                arg_expression TEXT,
                param_name     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_callargs_call ON call_args(call_id);
            CREATE TABLE IF NOT EXISTS dataflow_paths (
                id          INTEGER PRIMARY KEY,
                project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_var  TEXT    NOT NULL,
                sink_var    TEXT    NOT NULL,
                path_json   TEXT    NOT NULL,
                depth       INTEGER,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_dfpaths_project ON dataflow_paths(project_id);
            CREATE INDEX IF NOT EXISTS idx_dfpaths_source  ON dataflow_paths(source_var);
        """)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ── projects ──────────────────────────────────────────────────────────────

    def upsert_project(self, name: str, root_paths: str | list[str]) -> int:
        """Create or update a project with one or more root paths.

        Args:
            name: Project name (used as unique key).
            root_paths: A single root path string or a list of root path strings.
                        Stored as a JSON array in the DB.
        """
        if isinstance(root_paths, str):
            paths_json = json.dumps([root_paths])
        else:
            paths_json = json.dumps(list(root_paths))

        with self.transaction() as c:
            c.execute(
                """INSERT INTO projects(name, root_path)
                   VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET root_path=excluded.root_path""",
                (name, paths_json),
            )
            row = c.execute(
                "SELECT id FROM projects WHERE name=?", (name,)
            ).fetchone()
        return row["id"]

    def get_project_root_paths(self, project_id: int) -> list[str]:
        """Return the list of root paths for a project (deserialized from JSON)."""
        row = self._conn.execute(
            "SELECT root_path FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if row is None:
            return []
        rp = row["root_path"]
        if rp.startswith("["):
            return json.loads(rp)
        return [rp]

    def touch_project(self, project_id: int) -> None:
        self._conn.execute(
            "UPDATE projects SET last_indexed=CURRENT_TIMESTAMP WHERE id=?",
            (project_id,),
        )
        self._conn.commit()

    def get_project(self, project_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM projects ORDER BY name").fetchall()

    # ── files ─────────────────────────────────────────────────────────────────

    def upsert_file(
        self,
        project_id: int,
        path: str,
        relative_path: str,
        file_hash: str,
        last_modified: float,
        line_count: int,
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> int:
        def _do(c):
            c.execute(
                """INSERT INTO files(project_id, path, relative_path, file_hash,
                       last_modified, last_indexed, line_count)
                   VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,?)
                   ON CONFLICT(project_id, relative_path) DO UPDATE SET
                       file_hash     = excluded.file_hash,
                       last_modified = excluded.last_modified,
                       last_indexed  = CURRENT_TIMESTAMP,
                       line_count    = excluded.line_count""",
                (project_id, path, relative_path, file_hash, last_modified, line_count),
            )
            row = c.execute(
                "SELECT id FROM files WHERE project_id=? AND relative_path=?",
                (project_id, relative_path),
            ).fetchone()
            return row["id"]
        if _conn is not None:
            return _do(_conn)
        with self.transaction() as c:
            return _do(c)

    def get_file_hash(self, project_id: int, relative_path: str) -> str | None:
        row = self._conn.execute(
            "SELECT file_hash FROM files WHERE project_id=? AND relative_path=?",
            (project_id, relative_path),
        ).fetchone()
        return row["file_hash"] if row else None

    def get_all_file_hashes(self, project_id: int) -> dict[str, str]:
        """Load all file hashes for a project at once. Returns {relative_path: file_hash}."""
        rows = self._conn.execute(
            "SELECT relative_path, file_hash FROM files WHERE project_id=?",
            (project_id,),
        ).fetchall()
        return {row["relative_path"]: row["file_hash"] for row in rows}

    def list_files(self, project_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM files WHERE project_id=? ORDER BY relative_path",
            (project_id,),
        ).fetchall()

    def delete_file_symbols(self, file_id: int, *, _conn: sqlite3.Connection | None = None) -> None:
        def _do(c):
            c.execute("DELETE FROM calls WHERE call_file_id=?", (file_id,))
            c.execute("DELETE FROM config_sources WHERE file_id=?", (file_id,))
            c.execute("DELETE FROM config_usages WHERE file_id=?", (file_id,))
            c.execute(
                """DELETE FROM class_inheritance
                   WHERE class_symbol_id IN
                       (SELECT id FROM symbols WHERE file_id=?)""",
                (file_id,),
            )
            c.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
            c.execute("DELETE FROM includes WHERE file_id=?", (file_id,))
        if _conn is not None:
            _do(_conn)
            return
        with self.transaction() as c:
            _do(c)

    # ── symbols ───────────────────────────────────────────────────────────────

    def insert_symbol(
        self,
        file_id: int,
        name: str,
        qualified_name: str,
        kind: str,
        signature: str,
        line_start: int,
        line_end: int,
        col_start: int,
        is_definition: bool,
        is_declaration: bool,
        parent_id: int | None,
        namespace_path: str,
        visibility: str,
        return_type: str,
        usr: str,
        *,
        template_params: str = "",
        _conn: sqlite3.Connection | None = None,
    ) -> int:
        def _do(c):
            nonlocal parent_id
            if parent_id is not None:
                exists = c.execute(
                    "SELECT 1 FROM symbols WHERE id=?", (parent_id,)
                ).fetchone()
                if not exists:
                    parent_id = None
            cur = c.execute(
                """INSERT OR REPLACE INTO symbols(
                       file_id, name, qualified_name, kind, signature,
                       line_start, line_end, col_start,
                       is_definition, is_declaration,
                       parent_id, namespace_path, visibility, return_type, usr,
                       template_params)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    file_id, name, qualified_name, kind, signature,
                    line_start, line_end, col_start,
                    int(is_definition), int(is_declaration),
                    parent_id, namespace_path, visibility, return_type, usr,
                    template_params or None,
                ),
            )
            return cur.lastrowid
        if _conn is not None:
            return _do(_conn)
        with self.transaction() as c:
            return _do(c)

    def resolve_symbol_id(self, usr: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM symbols WHERE usr=?", (usr,)
        ).fetchone()
        return row["id"] if row else None

    def search_symbols(
        self,
        query: str,
        project_id: int | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT s.*, f.relative_path
            FROM symbols s
            JOIN files f ON s.file_id = f.id
        """
        params: list = []
        conditions = []
        if project_id is not None:
            conditions.append("f.project_id = ?")
            params.append(project_id)
        if kind:
            conditions.append("s.kind = ?")
            params.append(kind.upper())
        conditions.append("(s.name LIKE ? OR s.qualified_name LIKE ?)")
        like = f"%{query}%"
        params += [like, like]
        sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY s.name LIMIT ?"
        params.append(limit)
        return self._conn.execute(sql, params).fetchall()

    def get_symbol(self, symbol_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """SELECT s.*, f.relative_path, f.path
               FROM symbols s JOIN files f ON s.file_id=f.id
               WHERE s.id=?""",
            (symbol_id,),
        ).fetchone()

    # ── calls ─────────────────────────────────────────────────────────────────

    def insert_call(
        self,
        caller_id: int,
        callee_name: str,
        callee_id: int | None,
        call_file_id: int,
        call_line: int,
        call_col: int,
        code_snippet: str,
        *,
        call_type: str = "direct",
        _conn: sqlite3.Connection | None = None,
    ) -> None:
        def _do(c):
            c.execute(
                """INSERT OR IGNORE INTO calls(
                       caller_id, callee_name, callee_id,
                       call_file_id, call_line, call_col, code_snippet,
                       call_type)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (caller_id, callee_name, callee_id,
                 call_file_id, call_line, call_col, code_snippet,
                 call_type),
            )
        if _conn is not None:
            _do(_conn)
            return
        with self.transaction() as c:
            _do(c)

    def get_callees(self, symbol_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT c.*, s.qualified_name AS callee_qname,
                      f.relative_path AS callee_file
               FROM calls c
               LEFT JOIN symbols s ON c.callee_id = s.id
               LEFT JOIN files   f ON s.file_id   = f.id
               WHERE c.caller_id = ?
               ORDER BY c.call_line""",
            (symbol_id,),
        ).fetchall()

    def get_callers(self, symbol_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT c.*, s.qualified_name AS caller_qname,
                      f.relative_path AS caller_file
               FROM calls c
               JOIN symbols s ON c.caller_id = s.id
               JOIN files   f ON s.file_id   = f.id
               WHERE c.callee_id = ?
               ORDER BY c.call_line""",
            (symbol_id,),
        ).fetchall()

    # ── class inheritance ──────────────────────────────────────────────────

    def insert_inheritance(
        self,
        class_symbol_id: int,
        base_class_name: str,
        base_class_usr: str | None = None,
        base_class_id: int | None = None,
        access: str = "",
        is_virtual: bool = False,
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> None:
        def _do(c):
            c.execute(
                """INSERT OR IGNORE INTO class_inheritance(
                       class_symbol_id, base_class_name, base_class_usr,
                       base_class_id, access, is_virtual)
                   VALUES(?,?,?,?,?,?)""",
                (class_symbol_id, base_class_name, base_class_usr,
                 base_class_id, access, int(is_virtual)),
            )
        if _conn is not None:
            _do(_conn)
            return
        with self.transaction() as c:
            _do(c)

    def get_base_classes(self, symbol_id: int) -> list[sqlite3.Row]:
        """Return base classes of a given class symbol."""
        return self._conn.execute(
            """SELECT ci.*, s.qualified_name AS base_qname,
                      f.relative_path AS base_file
               FROM class_inheritance ci
               LEFT JOIN symbols s ON ci.base_class_id = s.id
               LEFT JOIN files   f ON s.file_id        = f.id
               WHERE ci.class_symbol_id = ?
               ORDER BY ci.base_class_name""",
            (symbol_id,),
        ).fetchall()

    def get_derived_classes(self, symbol_id: int) -> list[sqlite3.Row]:
        """Return derived classes of a given class symbol."""
        return self._conn.execute(
            """SELECT ci.*, s.qualified_name AS derived_qname,
                      f.relative_path AS derived_file
               FROM class_inheritance ci
               JOIN symbols s ON ci.class_symbol_id = s.id
               JOIN files   f ON s.file_id          = f.id
               WHERE ci.base_class_id = ?
               ORDER BY s.qualified_name""",
            (symbol_id,),
        ).fetchall()

    def all_calls(self, project_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT c.caller_id, c.callee_id
               FROM calls c
               JOIN files f ON c.call_file_id = f.id
               WHERE f.project_id = ? AND c.callee_id IS NOT NULL""",
            (project_id,),
        ).fetchall()

    # ── includes ──────────────────────────────────────────────────────────────

    def insert_include(
        self,
        file_id: int,
        included_file_id: int | None,
        included_path: str,
        line: int,
        is_system: bool,
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> None:
        def _do(c):
            c.execute(
                """INSERT OR IGNORE INTO includes(
                       file_id, included_file_id, included_path, line, is_system)
                   VALUES(?,?,?,?,?)""",
                (file_id, included_file_id, included_path, line, int(is_system)),
            )
        if _conn is not None:
            _do(_conn)
            return
        with self.transaction() as c:
            _do(c)

    def resolve_include_file_ids(self, project_id: int) -> int:
        """Match included_path to files.relative_path and UPDATE included_file_id.

        Uses basename or suffix matching for flexibility.
        Returns the number of resolved includes.
        """
        # Get all unresolved includes for this project
        unresolved = self._conn.execute(
            """SELECT i.id, i.included_path
               FROM includes i
               JOIN files f ON i.file_id = f.id
               WHERE f.project_id = ? AND i.included_file_id IS NULL
                 AND i.is_system = 0""",
            (project_id,),
        ).fetchall()

        if not unresolved:
            return 0

        # Build lookup from relative_path and basename
        files = self._conn.execute(
            "SELECT id, relative_path FROM files WHERE project_id=?",
            (project_id,),
        ).fetchall()

        # suffix -> file_id (last component match, then full suffix match)
        basename_map: dict[str, list[int]] = {}
        relpath_map: dict[str, int] = {}
        for f in files:
            rp = f["relative_path"]
            relpath_map[rp] = f["id"]
            import os
            bn = os.path.basename(rp)
            basename_map.setdefault(bn, []).append(f["id"])

        resolved = 0
        with self.transaction() as c:
            for row in unresolved:
                inc_path = row["included_path"]
                fid: int | None = None

                # 1. Exact relative_path match
                if inc_path in relpath_map:
                    fid = relpath_map[inc_path]
                else:
                    # 2. Suffix match: find files whose relative_path ends with inc_path
                    for rp, rid in relpath_map.items():
                        if rp.endswith("/" + inc_path) or rp == inc_path:
                            fid = rid
                            break

                    # 3. Basename match
                    if fid is None:
                        bn = os.path.basename(inc_path)
                        candidates = basename_map.get(bn, [])
                        if len(candidates) == 1:
                            fid = candidates[0]

                if fid is not None:
                    c.execute(
                        "UPDATE includes SET included_file_id=? WHERE id=?",
                        (fid, row["id"]),
                    )
                    resolved += 1

        return resolved

    def all_includes(self, project_id: int, include_system: bool = False) -> list[sqlite3.Row]:
        """Return all include edges for a project (file_id -> included_file_id).

        Only returns rows where included_file_id is resolved (not NULL).
        """
        sql = """SELECT i.file_id, i.included_file_id, i.included_path, i.is_system
                 FROM includes i
                 JOIN files f ON i.file_id = f.id
                 WHERE f.project_id = ? AND i.included_file_id IS NOT NULL"""
        if not include_system:
            sql += " AND i.is_system = 0"
        return self._conn.execute(sql, (project_id,)).fetchall()

    def get_file_by_path(self, project_id: int, path_pattern: str) -> list[sqlite3.Row]:
        """Search files by path pattern (LIKE match on relative_path)."""
        return self._conn.execute(
            """SELECT * FROM files
               WHERE project_id = ? AND relative_path LIKE ?
               ORDER BY relative_path""",
            (project_id, f"%{path_pattern}%"),
        ).fetchall()

    def get_file(self, file_id: int) -> sqlite3.Row | None:
        """Get a single file by ID."""
        return self._conn.execute(
            "SELECT * FROM files WHERE id=?", (file_id,)
        ).fetchone()

    # ── parse entity cache ────────────────────────────────────────────────────

    def get_parse_cache(self, file_id: int, file_hash: str) -> dict | None:
        """Return cached entity payload if hash matches, else None."""
        row = self._conn.execute(
            "SELECT file_hash, payload FROM parse_cache WHERE file_id=?",
            (file_id,),
        ).fetchone()
        if row is None or row["file_hash"] != file_hash:
            return None
        try:
            return json.loads(row["payload"])
        except (ValueError, TypeError):
            return None

    def upsert_parse_cache(
        self, file_id: int, file_hash: str, payload: dict
    ) -> None:
        self._conn.execute(
            """INSERT INTO parse_cache(file_id, file_hash, payload)
                   VALUES(?,?,?)
               ON CONFLICT(file_id) DO UPDATE SET
                   file_hash=excluded.file_hash,
                   payload=excluded.payload,
                   created_at=CURRENT_TIMESTAMP""",
            (file_id, file_hash, json.dumps(payload)),
        )
        self._conn.commit()

    def invalidate_parse_cache(self, file_id: int) -> None:
        self._conn.execute("DELETE FROM parse_cache WHERE file_id=?", (file_id,))
        self._conn.commit()

    # ── config scan state (hash-gate) ─────────────────────────────────────────

    def get_config_scan_state(self, project_id: int) -> dict[int, str]:
        rows = self._conn.execute(
            """SELECT s.file_id, s.scan_hash FROM config_scan_state s
                   JOIN files f ON f.id = s.file_id
               WHERE f.project_id = ?""",
            (project_id,),
        ).fetchall()
        return {r["file_id"]: r["scan_hash"] for r in rows}

    def mark_config_scanned(self, file_id: int, scan_hash: str) -> None:
        self._conn.execute(
            """INSERT INTO config_scan_state(file_id, scan_hash)
                   VALUES(?,?)
               ON CONFLICT(file_id) DO UPDATE SET
                   scan_hash=excluded.scan_hash,
                   scanned_at=CURRENT_TIMESTAMP""",
            (file_id, scan_hash),
        )
        self._conn.commit()

    # ── trace result cache ────────────────────────────────────────────────────

    def compute_project_fingerprint(self, project_id: int) -> str:
        """Aggregate hash of all (file_id, file_hash) for the project.
        Any file change flips this value, invalidating dependent caches."""
        import hashlib
        rows = self._conn.execute(
            "SELECT id, file_hash FROM files WHERE project_id=? ORDER BY id",
            (project_id,),
        ).fetchall()
        h = hashlib.sha256()
        for r in rows:
            h.update(f"{r['id']}:{r['file_hash'] or ''}\n".encode())
        return h.hexdigest()

    def get_trace_result(
        self, project_id: int, key_hash: str, fingerprint: str
    ) -> list[dict] | None:
        row = self._conn.execute(
            """SELECT paths_json, fingerprint FROM trace_result_cache
               WHERE project_id=? AND key_hash=?""",
            (project_id, key_hash),
        ).fetchone()
        if row is None or row["fingerprint"] != fingerprint:
            return None
        try:
            return json.loads(row["paths_json"])
        except (ValueError, TypeError):
            return None

    def upsert_trace_result(
        self,
        project_id: int,
        key_hash: str,
        fingerprint: str,
        paths: list[dict],
    ) -> None:
        self._conn.execute(
            """INSERT INTO trace_result_cache(project_id, key_hash, fingerprint, paths_json)
                   VALUES(?,?,?,?)
               ON CONFLICT(project_id, key_hash) DO UPDATE SET
                   fingerprint=excluded.fingerprint,
                   paths_json=excluded.paths_json,
                   created_at=CURRENT_TIMESTAMP""",
            (project_id, key_hash, fingerprint, json.dumps(paths)),
        )
        self._conn.commit()

    def clear_trace_cache(self, project_id: int) -> None:
        self._conn.execute(
            "DELETE FROM trace_result_cache WHERE project_id=?", (project_id,)
        )
        self._conn.commit()

    # ── config patterns ───────────────────────────────────────────────────────

    def sync_config_patterns(self, patterns: list[dict]) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM config_patterns")
            for p in patterns:
                c.execute(
                    """INSERT INTO config_patterns(
                           name, pattern_type, description, regex, key_group)
                       VALUES(?,?,?,?,?)""",
                    (
                        p["name"],
                        p["type"],
                        p.get("description", ""),
                        p["regex"],
                        p.get("key_group", 1),
                    ),
                )

    def get_active_config_patterns(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM config_patterns WHERE is_active=1"
        ).fetchall()

    # ── config sources ────────────────────────────────────────────────────────

    def insert_config_source(
        self,
        project_id: int,
        file_id: int,
        symbol_id: int | None,
        pattern_id: int | None,
        config_key: str,
        line: int,
        col: int,
        code_snippet: str,
    ) -> int:
        with self.transaction() as c:
            c.execute(
                """INSERT OR IGNORE INTO config_sources(
                       project_id, file_id, symbol_id, pattern_id,
                       config_key, line, col, code_snippet)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (project_id, file_id, symbol_id, pattern_id,
                 config_key, line, col, code_snippet),
            )
            row = c.execute(
                """SELECT id FROM config_sources
                   WHERE file_id=? AND line=? AND col=? AND config_key=?""",
                (file_id, line, col, config_key),
            ).fetchone()
            return row["id"] if row else c.lastrowid

    def list_config_keys(self, project_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT DISTINCT cs.config_key,
                      COUNT(*) as source_count,
                      cp.pattern_type
               FROM config_sources cs
               JOIN config_patterns cp ON cs.pattern_id = cp.id
               WHERE cs.project_id=?
               GROUP BY cs.config_key
               ORDER BY cs.config_key""",
            (project_id,),
        ).fetchall()

    def get_config_sources(
        self, project_id: int, config_key: str
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT cs.*, f.relative_path, s.qualified_name AS enclosing_fn,
                      cp.name AS pattern_name, cp.pattern_type
               FROM config_sources cs
               JOIN files f ON cs.file_id = f.id
               LEFT JOIN symbols s ON cs.symbol_id = s.id
               LEFT JOIN config_patterns cp ON cs.pattern_id = cp.id
               WHERE cs.project_id=? AND cs.config_key=?
               ORDER BY f.relative_path, cs.line""",
            (project_id, config_key),
        ).fetchall()

    def insert_config_usage(
        self,
        source_id: int | None,
        file_id: int,
        symbol_id: int | None,
        config_key: str,
        usage_type: str,
        affects_control_flow: bool,
        line: int,
        col: int,
        code_snippet: str,
    ) -> None:
        with self.transaction() as c:
            c.execute(
                """INSERT OR IGNORE INTO config_usages(
                       source_id, file_id, symbol_id, config_key,
                       usage_type, affects_control_flow, line, col, code_snippet)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (source_id, file_id, symbol_id, config_key,
                 usage_type, int(affects_control_flow), line, col, code_snippet),
            )

    def get_config_usages(
        self, project_id: int, config_key: str
    ) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT cu.*, f.relative_path, s.qualified_name AS fn_name
               FROM config_usages cu
               JOIN files f ON cu.file_id = f.id
               LEFT JOIN symbols s ON cu.symbol_id = s.id
               WHERE f.project_id=? AND cu.config_key=?
               ORDER BY f.relative_path, cu.line""",
            (project_id, config_key),
        ).fetchall()

    # ── call args ─────────────────────────────────────────────────────────────

    def insert_call_arg(
        self,
        call_id: int,
        arg_index: int,
        arg_expression: str,
        param_name: str = "",
        *,
        _conn: sqlite3.Connection | None = None,
    ) -> None:
        def _do(c):
            c.execute(
                """INSERT OR IGNORE INTO call_args(
                       call_id, arg_index, arg_expression, param_name)
                   VALUES(?,?,?,?)""",
                (call_id, arg_index, arg_expression, param_name),
            )
        if _conn is not None:
            _do(_conn)
            return
        with self.transaction() as c:
            _do(c)

    def get_call_args(self, call_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM call_args WHERE call_id=? ORDER BY arg_index",
            (call_id,),
        ).fetchall()

    # ── dataflow paths ────────────────────────────────────────────────────────

    def insert_dataflow_path(
        self,
        project_id: int,
        source_var: str,
        sink_var: str,
        path_json: str,
        depth: int,
    ) -> int:
        with self.transaction() as c:
            cur = c.execute(
                """INSERT INTO dataflow_paths(
                       project_id, source_var, sink_var, path_json, depth)
                   VALUES(?,?,?,?,?)""",
                (project_id, source_var, sink_var, path_json, depth),
            )
            return cur.lastrowid

    def get_dataflow_paths(
        self,
        project_id: int,
        source_var: str | None = None,
        sink_var: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM dataflow_paths WHERE project_id=?"
        params: list = [project_id]
        if source_var:
            sql += " AND source_var LIKE ?"
            params.append(f"%{source_var}%")
        if sink_var:
            sql += " AND sink_var LIKE ?"
            params.append(f"%{sink_var}%")
        sql += " ORDER BY source_var, sink_var"
        return self._conn.execute(sql, params).fetchall()

    def delete_dataflow_paths(self, project_id: int) -> int:
        with self.transaction() as c:
            cur = c.execute(
                "DELETE FROM dataflow_paths WHERE project_id=?",
                (project_id,),
            )
            return cur.rowcount

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self, project_id: int) -> dict:
        c = self._conn
        def scalar(sql, *args):
            r = c.execute(sql, args).fetchone()
            return r[0] if r else 0

        return {
            "files":          scalar("SELECT COUNT(*) FROM files WHERE project_id=?", project_id),
            "symbols":        scalar("SELECT COUNT(*) FROM symbols s JOIN files f ON s.file_id=f.id WHERE f.project_id=?", project_id),
            "functions":      scalar("SELECT COUNT(*) FROM symbols s JOIN files f ON s.file_id=f.id WHERE f.project_id=? AND s.kind IN ('FUNCTION','METHOD','CONSTRUCTOR')", project_id),
            "classes":        scalar("SELECT COUNT(*) FROM symbols s JOIN files f ON s.file_id=f.id WHERE f.project_id=? AND s.kind IN ('CLASS','STRUCT')", project_id),
            "calls":          scalar("SELECT COUNT(*) FROM calls c JOIN files f ON c.call_file_id=f.id WHERE f.project_id=?", project_id),
            "config_keys":    scalar("SELECT COUNT(DISTINCT config_key) FROM config_sources WHERE project_id=?", project_id),
            "config_sources": scalar("SELECT COUNT(*) FROM config_sources WHERE project_id=?", project_id),
            "config_usages":  scalar("SELECT COUNT(*) FROM config_usages cu JOIN files f ON cu.file_id=f.id WHERE f.project_id=?", project_id),
            "dataflow_paths": scalar("SELECT COUNT(*) FROM dataflow_paths WHERE project_id=?", project_id),
        }
