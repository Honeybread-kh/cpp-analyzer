"""
Config Dependency Analyzer: combines tree-sitter AST analysis with
cpp-analyzer's indexed DB to detect configuration parameters,
their dependencies, and forced value overrides.

Usage:
    analyzer = ConfigDependencyAnalyzer(repo, project_id)
    result = analyzer.analyze()
    # result.configs  -> list[ConfigParam]
    # result.dependencies -> list[ConfigDependency]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..db.repository import Repository
from .models import ConfigParam, ConfigDependency
from . import ts_parser


@dataclass
class AnalysisResult:
    configs: list[ConfigParam] = field(default_factory=list)
    dependencies: list[ConfigDependency] = field(default_factory=list)


class ConfigDependencyAnalyzer:
    def __init__(
        self,
        repo: Repository,
        project_id: int,
        target_structs: list[str] | None = None,
    ):
        self.repo = repo
        self.project_id = project_id
        # user can specify target struct names; else we auto-detect
        self.target_structs = target_structs or []
        self._configs: dict[str, ConfigParam] = {}
        self._deps: list[ConfigDependency] = []
        self._struct_fields: dict[str, set[str]] = {}  # struct -> {field names}

    def analyze(self) -> AnalysisResult:
        """Run full analysis pipeline."""
        files = self.repo.list_files(self.project_id)
        project = self.repo.get_project(self.project_id)
        if project:
            rp = project["root_path"]
            root_paths = json.loads(rp) if rp.startswith("[") else [rp]
        else:
            root_paths = []

        # Phase 1: Extract struct fields from headers
        for f in files:
            if f["relative_path"].endswith((".h", ".hpp", ".hxx")):
                self._analyze_struct_fields(f["path"], f["relative_path"])

        # Phase 2: Extract CLI arg → field mappings from source files
        for f in files:
            if f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                self._analyze_cli_handlers(f["path"], f["relative_path"])

        # Phase 3: Extract default values from init functions
        for f in files:
            if f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                self._analyze_defaults(f["path"], f["relative_path"])

        # Phase 4: Detect overrides and dependencies
        for f in files:
            if f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                self._analyze_overrides(f["path"], f["relative_path"])

        # Phase 5: Detect cascading patterns
        for f in files:
            if f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                self._analyze_cascades(f["path"], f["relative_path"])

        # Phase 6: Detect aggregation (CLI handlers setting multiple fields)
        self._detect_aggregations()

        # Phase 7: Cross-function override detection via call graph
        self._analyze_cross_function_overrides()

        # Phase 8: Self-override detection (same var reassigned conditionally)
        for f in files:
            if f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                self._analyze_self_overrides(f["path"], f["relative_path"])

        return AnalysisResult(
            configs=list(self._configs.values()),
            dependencies=self._deps,
        )

    # ── Phase 1: Struct fields ──────────────────────────────────────────────

    def _analyze_struct_fields(self, file_path: str, rel_path: str) -> None:
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        fields = ts_parser.extract_struct_fields(root)
        for f in fields:
            struct_name = f["struct_name"]

            # auto-detect or match target structs
            if self.target_structs:
                if not any(t in struct_name for t in self.target_structs):
                    continue
            else:
                # heuristic: skip small internal structs
                if struct_name.startswith("_"):
                    continue

            self._struct_fields.setdefault(struct_name, set()).add(f["field_name"])

            key = f"{struct_name}.{f['field_name']}"
            if key not in self._configs:
                self._configs[key] = ConfigParam(
                    name=f["field_name"],
                    qualified_name=key,
                    config_type=f["field_type"],
                    source_kind="STRUCT_FIELD",
                    defined_file=rel_path,
                    defined_line=f["line"],
                    description=f["comment"],
                )

    # ── Phase 2: CLI handlers ───────────────────────────────────────────────

    def _analyze_cli_handlers(self, file_path: str, rel_path: str) -> None:
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        handlers = ts_parser.extract_cli_handler_assignments(root)
        for h in handlers:
            for a in h["assignments"]:
                field_name = a["field_name"]
                matched = self._find_config_by_field(field_name)
                if matched:
                    matched.cli_flag = h["cli_flag"]
                    if matched.source_kind == "STRUCT_FIELD":
                        matched.source_kind = "CLI_ARG"

    # ── Phase 3: Default values ─────────────────────────────────────────────

    def _analyze_defaults(self, file_path: str, rel_path: str) -> None:
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        bulk = ts_parser.extract_bulk_assignments(root, min_count=3)
        for b in bulk:
            func_name = b["function_name"]
            for a in b["assignments"]:
                matched = self._find_config_by_field(a["field"])
                if matched:
                    if matched.default_value is None:
                        matched.default_value = a["value"]
                    if matched.setter_function is None:
                        matched.setter_function = func_name

    # ── Phase 4: Direct overrides ───────────────────────────────────────────

    def _analyze_overrides(self, file_path: str, rel_path: str) -> None:
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        overrides = ts_parser.extract_if_field_overrides(root)
        for o in overrides:
            source = self._find_config_by_field(o["source_field"])
            target = self._find_config_by_field(o["target_field"])

            source_name = source.qualified_name if source else o["source_field"]
            target_name = target.qualified_name if target else o["target_field"]

            # find enclosing function from DB
            func_name = self._find_function_at(file_path, o["line"])

            self._deps.append(ConfigDependency(
                source_config=source_name,
                source_condition=f"{o['condition_op']} {o['condition_value']}",
                target_config=target_name,
                forced_value=o["forced_value"],
                relationship_type="DIRECT_OVERRIDE",
                file=rel_path,
                line=o["line"],
                function=func_name,
                code_snippet=o["code_snippet"],
            ))

    # ── Phase 5: Cascade patterns ───────────────────────────────────────────

    def _analyze_cascades(self, file_path: str, rel_path: str) -> None:
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        cascades = ts_parser.extract_cascade_patterns(root)
        for c in cascades:
            source = self._find_config_by_field(c["switch_field"])
            source_name = source.qualified_name if source else c["switch_field"]

            for branch in c["branches"]:
                for a in branch["assignments"]:
                    target = self._find_config_by_field(a["field"])
                    target_name = target.qualified_name if target else a["field"]

                    self._deps.append(ConfigDependency(
                        source_config=source_name,
                        source_condition=f"== {branch['case_value']}",
                        target_config=target_name,
                        forced_value=a["value"],
                        relationship_type="CASCADE",
                        file=rel_path,
                        line=c["line"],
                        function=c["function"],
                        code_snippet=f"switch({c['switch_field']}) case {branch['case_value']}",
                    ))

    # ── Phase 6: Aggregation ────────────────────────────────────────────────

    def _detect_aggregations(self) -> None:
        """Re-classify dependencies where one CLI flag sets 3+ fields."""
        cli_groups: dict[str, list[ConfigDependency]] = {}
        for dep in self._deps:
            if dep.relationship_type == "DIRECT_OVERRIDE":
                # check if source is a CLI flag
                source_cfg = self._configs.get(dep.source_config)
                if source_cfg and source_cfg.cli_flag:
                    cli_groups.setdefault(source_cfg.cli_flag, []).append(dep)

        for flag, deps in cli_groups.items():
            if len(deps) >= 3:
                for dep in deps:
                    dep.relationship_type = "AGGREGATION"

        # Also check cli handlers that were detected with multiple assignments
        # These are captured in the CLI handler analysis but may not have created deps
        # Aggregate them from _configs where multiple fields share same cli_flag
        flag_configs: dict[str, list[ConfigParam]] = {}
        for cfg in self._configs.values():
            if cfg.cli_flag:
                flag_configs.setdefault(cfg.cli_flag, []).append(cfg)

        for flag, cfgs in flag_configs.items():
            if len(cfgs) >= 3:
                # ensure we have aggregation deps for these
                existing_targets = {
                    d.target_config
                    for d in self._deps
                    if d.source_config == flag or (
                        self._configs.get(d.source_config, ConfigParam("")).cli_flag == flag
                    )
                }
                for cfg in cfgs:
                    if cfg.qualified_name not in existing_targets:
                        self._deps.append(ConfigDependency(
                            source_config=flag,
                            target_config=cfg.qualified_name,
                            relationship_type="AGGREGATION",
                            code_snippet=f"CLI flag {flag} sets {cfg.name}",
                        ))

    # ── Phase 7: Cross-function overrides ───────────────────────────────────

    def _analyze_cross_function_overrides(self) -> None:
        """Use call graph to detect overrides across function boundaries.

        Example: parse_switches calls jpeg_simple_progression(),
        which internally sets lossless = FALSE.
        """
        # Get all known config fields
        known_fields = set()
        for cfg in self._configs.values():
            known_fields.add(cfg.name)

        # Find functions that do bulk assignments (potential override functions)
        files = self.repo.list_files(self.project_id)
        override_funcs: dict[str, list[dict]] = {}  # func_name -> [{field, value}]

        for f in files:
            if not f["relative_path"].endswith((".c", ".cpp", ".cc", ".cxx")):
                continue
            root = ts_parser.parse_file(f["path"])
            if root is None:
                continue

            bulk = ts_parser.extract_bulk_assignments(root, min_count=2)
            for b in bulk:
                relevant = [
                    a for a in b["assignments"]
                    if a["field"] in known_fields
                ]
                if relevant:
                    override_funcs[b["function_name"]] = relevant

        # Check call graph: who calls these override functions?
        for func_name, assignments in override_funcs.items():
            # find symbol for this function
            symbols = self.repo.search_symbols(func_name, project_id=self.project_id, kind="FUNCTION", limit=5)
            for sym in symbols:
                if sym["name"] != func_name:
                    continue
                callers = self.repo.get_callers(sym["id"])
                for caller in callers:
                    caller_name = caller["caller_qname"] or ""
                    for a in assignments:
                        target = self._find_config_by_field(a["field"])
                        if target:
                            # avoid duplicates
                            exists = any(
                                d.function == func_name
                                and d.target_config == target.qualified_name
                                for d in self._deps
                            )
                            if not exists:
                                self._deps.append(ConfigDependency(
                                    source_config=f"call:{func_name}()",
                                    target_config=target.qualified_name,
                                    forced_value=a["value"],
                                    relationship_type="MUTUAL_EXCLUSION",
                                    file=caller["caller_file"] or "",
                                    line=caller["call_line"] or 0,
                                    function=func_name,
                                    code_snippet=f"{caller_name} calls {func_name}() which sets {a['field']}={a['value']}",
                                ))

    # ── helpers ──────────────────────────────────────────────────────────────

    # ── Phase 8: Self-override detection ───────────────────────────────────

    def _analyze_self_overrides(self, file_path: str, rel_path: str) -> None:
        """Detect cases where a config field that was set by user input
        (CLI arg, default, etc.) gets conditionally reassigned to a different value.

        Example: user sets data_precision=12 via -precision flag,
        but internal code does: if (lossless && precision > 12) precision = 12;

        This produces SELF_OVERRIDE dependency type.
        """
        root = ts_parser.parse_file(file_path)
        if root is None:
            return

        overrides = ts_parser.extract_self_overrides(root)
        for o in overrides:
            target = self._find_config_by_field(o["target_field"])
            if target is None:
                continue

            # Only report if this config has a known source (CLI or default)
            if not target.cli_flag and not target.setter_function:
                continue

            # Build condition description from referenced fields
            cond_fields = o["condition_fields"]
            cond_configs = []
            for cf in cond_fields:
                cc = self._find_config_by_field(cf)
                if cc:
                    cond_configs.append(cc.qualified_name)

            # Avoid duplicating existing DIRECT_OVERRIDE entries
            exists = any(
                d.target_config == target.qualified_name
                and d.forced_value == o["forced_value"]
                and d.line == o["line"]
                for d in self._deps
            )
            if exists:
                continue

            source_desc = ", ".join(cond_configs) if cond_configs else o["condition_text"]

            self._deps.append(ConfigDependency(
                source_config=source_desc,
                source_condition=o["condition_text"],
                target_config=target.qualified_name,
                forced_value=o["forced_value"],
                relationship_type="SELF_OVERRIDE",
                file=rel_path,
                line=o["line"],
                function=o["enclosing_function"],
                code_snippet=o["code_snippet"],
            ))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_config_by_field(self, field_name: str) -> ConfigParam | None:
        """Find a ConfigParam by its unqualified field name."""
        for key, cfg in self._configs.items():
            if cfg.name == field_name:
                return cfg
        return None

    def _find_function_at(self, file_path: str, line: int) -> str:
        """Find enclosing function name at a given line using the DB."""
        # look up file_id
        p = Path(file_path)
        row = self.repo._conn.execute(
            "SELECT id FROM files WHERE path=? OR path LIKE ?",
            (str(p), f"%{p.name}"),
        ).fetchone()
        if not row:
            return ""

        sym = self.repo._conn.execute(
            """SELECT name, qualified_name FROM symbols
               WHERE file_id=?
                 AND kind IN ('FUNCTION','METHOD')
                 AND line_start <= ? AND line_end >= ?
               ORDER BY (line_end - line_start) ASC LIMIT 1""",
            (row["id"], line, line),
        ).fetchone()
        return (sym["qualified_name"] or sym["name"]) if sym else ""
