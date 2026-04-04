"""
Config Tracker: scans C++ source lines for config access patterns
(getenv, map lookups, gflags, CLI args, JSON, preprocessor macros …)
and records them in config_sources / config_usages tables.

Pattern matching is done with the regexes loaded from config_patterns.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from ..db.repository import Repository


# ── result types ─────────────────────────────────────────────────────────────

class ConfigHit(NamedTuple):
    pattern_id: int
    pattern_name: str
    pattern_type: str
    config_key: str
    line: int
    col: int
    code_snippet: str
    is_condition: bool   # does the line contain if/while/switch/ternary?
    usage_type: str      # CONDITION | ASSIGNMENT | CALL_ARG | RETURN | DEFINITION | OTHER


_CONDITION_RE  = re.compile(r'\b(if|while|switch|for|\?)\b')
_ASSIGNMENT_RE = re.compile(r'[^=!<>]=(?!=)')
_RETURN_RE     = re.compile(r'\breturn\b')
_CALL_ARG_RE   = re.compile(r'\w+\s*\(')


def _classify_usage(line: str) -> tuple[bool, str]:
    is_cond = bool(_CONDITION_RE.search(line))
    if is_cond:
        return True, "CONDITION"
    if _RETURN_RE.search(line):
        return False, "RETURN"
    if _ASSIGNMENT_RE.search(line):
        return False, "ASSIGNMENT"
    if _CALL_ARG_RE.search(line):
        return False, "CALL_ARG"
    return False, "OTHER"


class ConfigTracker:
    def __init__(self, repo: Repository, project_id: int):
        self.repo = repo
        self.project_id = project_id
        self._patterns = self._load_compiled_patterns()

    # ── public API ────────────────────────────────────────────────────────────

    def scan_file(self, file_path: str | Path) -> list[ConfigHit]:
        """Scan source file and record all config hits in the DB."""
        path = str(file_path)
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

        # resolve file_id from DB
        from ..db.repository import Repository
        row = self.repo._conn.execute(
            """SELECT f.id, f.project_id FROM files f
               WHERE f.path=? OR f.path LIKE ?""",
            (path, f"%{Path(path).name}"),
        ).fetchone()
        if row is None:
            return []
        file_id = row["id"]

        hits: list[ConfigHit] = []
        for lineno, raw_line in enumerate(lines, 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            for (pid, pname, ptype, regex, grp) in self._patterns:
                for m in regex.finditer(raw_line):
                    try:
                        key = m.group(grp)
                    except IndexError:
                        key = m.group(0)
                    col = m.start() + 1
                    is_cond, usage_type = _classify_usage(raw_line)
                    hit = ConfigHit(
                        pattern_id   = pid,
                        pattern_name = pname,
                        pattern_type = ptype,
                        config_key   = key,
                        line         = lineno,
                        col          = col,
                        code_snippet = raw_line.rstrip(),
                        is_condition = is_cond,
                        usage_type   = usage_type,
                    )
                    hits.append(hit)

                    # find enclosing function
                    sym_id = self._find_enclosing_function(file_id, lineno)

                    # write config_source
                    source_id = self.repo.insert_config_source(
                        project_id   = self.project_id,
                        file_id      = file_id,
                        symbol_id    = sym_id,
                        pattern_id   = pid,
                        config_key   = key,
                        line         = lineno,
                        col          = col,
                        code_snippet = raw_line.rstrip(),
                    )

                    # write config_usage
                    self.repo.insert_config_usage(
                        source_id            = source_id,
                        file_id              = file_id,
                        symbol_id            = sym_id,
                        config_key           = key,
                        usage_type           = usage_type,
                        affects_control_flow = is_cond,
                        line                 = lineno,
                        col                  = col,
                        code_snippet         = raw_line.rstrip(),
                    )
        return hits

    def scan_all(self) -> int:
        """Scan every file in the project. Returns total hit count."""
        files = self.repo.list_files(self.project_id)
        total = 0
        for f in files:
            hits = self.scan_file(f["path"])
            total += len(hits)
        return total

    # ── helpers ───────────────────────────────────────────────────────────────

    def _load_compiled_patterns(self) -> list[tuple[int, str, str, re.Pattern, int]]:
        rows = self.repo.get_active_config_patterns()
        out = []
        for r in rows:
            try:
                compiled = re.compile(r["regex"])
                out.append((r["id"], r["name"], r["pattern_type"], compiled, r["key_group"]))
            except re.error:
                pass
        return out

    def _find_enclosing_function(self, file_id: int, line: int) -> int | None:
        row = self.repo._conn.execute(
            """SELECT id FROM symbols
               WHERE file_id=?
                 AND kind IN ('FUNCTION','METHOD','CONSTRUCTOR','DESTRUCTOR','FUNCTION_TEMPLATE')
                 AND line_start <= ?
                 AND line_end   >= ?
               ORDER BY (line_end - line_start) ASC
               LIMIT 1""",
            (file_id, line, line),
        ).fetchone()
        return row["id"] if row else None
