"""
Taint analysis engine for multi-stage dataflow tracking.

Traces how config fields propagate through intermediate variables and function
calls to reach final sinks (e.g. register writes).  Works with tree-sitter
parsed C/C++ code and the existing call graph infrastructure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ts_parser
from .models import TaintNode, DataFlowPath
from ..db.repository import Repository


# ── default source / sink patterns ────────────────────────────────────────────

DEFAULT_SOURCE_PATTERNS: list[dict] = [
    {"name": "config_field",     "regex": r"(?:cfg|config|conf|param)\w*->(\w+)"},
    {"name": "config_dot",       "regex": r"(?:cfg|config|conf|param)\w*\.(\w+)"},
]

DEFAULT_SINK_PATTERNS: list[dict] = [
    {"name": "REG_WRITE",        "regex": r"REG_WRITE\s*\(\s*([^,]+)\s*,"},
    {"name": "WRITE_REG",        "regex": r"WRITE_REG\s*\(\s*([^,]+)\s*,"},
    {"name": "SET_SWI_FIELD",    "regex": r"SET_SWI_FIELD\s*\("},
    {"name": "reg_arrow_assign", "regex": r"(?:reg|regs|hw_reg)\w*->(\w+)\s*="},
    {"name": "reg_dot_assign",   "regex": r"(?:reg|regs|hw_reg)\w*\.(\w+)\s*="},
]


def load_patterns_yaml(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Load source/sink patterns from a YAML file.

    Expected format:
        sources:
          - name: config_field
            regex: 'cfg->(\w+)'
        sinks:
          - name: REG_WRITE
            regex: 'REG_WRITE\s*\('

    Returns (source_patterns, sink_patterns).
    """
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    sources = data.get("sources", [])
    sinks = data.get("sinks", [])
    if not sources and not sinks:
        raise ValueError(f"No sources or sinks found in {path}")
    return sources, sinks


# ── pointer alias map ────────────────────────────────────────────────────────

class AliasMap:
    """Track pointer aliases within a single function scope."""

    def __init__(self):
        self._map: dict[str, str] = {}  # alias -> origin

    def add(self, alias: str, origin: str) -> None:
        resolved = self.resolve(origin)
        self._map[alias] = resolved

    def resolve(self, var: str) -> str:
        """Follow alias chain to the original variable."""
        seen: set[str] = set()
        while var in self._map and var not in seen:
            seen.add(var)
            var = self._map[var]
        return var

    def resolve_field(self, expr: str) -> str:
        """Resolve 'p->field' using alias map for 'p'.

        E.g. if p is aliased to config, 'p->field' becomes 'config->field'.
        """
        for sep in ("->", "."):
            if sep in expr:
                parts = expr.split(sep, 1)
                resolved_base = self.resolve(parts[0].strip())
                if resolved_base != parts[0].strip():
                    return f"{resolved_base}{sep}{parts[1]}"
                return expr
        return self.resolve(expr)

    def __repr__(self) -> str:
        return f"AliasMap({self._map})"


# ── taint tracker ─────────────────────────────────────────────────────────────

class TaintTracker:
    """Multi-stage dataflow tracker: source (config) → sink (register)."""

    def __init__(
        self,
        repo: Repository,
        project_id: int,
        source_patterns: list[dict] | None = None,
        sink_patterns: list[dict] | None = None,
    ):
        self.repo = repo
        self.project_id = project_id
        self.source_patterns = source_patterns or DEFAULT_SOURCE_PATTERNS
        self.sink_patterns = sink_patterns or DEFAULT_SINK_PATTERNS

        self._compiled_sources = [
            re.compile(p["regex"]) for p in self.source_patterns
        ]
        self._compiled_sinks = [
            re.compile(p["regex"]) for p in self.sink_patterns
        ]

        # caches populated during trace
        self._file_assignments: dict[str, list[dict]] = {}  # path -> assignments
        self._file_calls: dict[str, list[dict]] = {}        # path -> call args
        self._file_params: dict[str, list[dict]] = {}       # path -> function params
        self._file_returns: dict[str, list[dict]] = {}      # path -> return stmts
        self._func_to_file: dict[str, str] = {}             # func_name -> file path

    def trace(self, max_depth: int = 5, max_paths: int = 100) -> list[DataFlowPath]:
        """Run full taint analysis across the project.

        1. Scan all files for sink patterns
        2. From each sink, trace backward through assignments
        3. Cross function boundaries via call graph
        4. Stop when a source pattern is matched or depth limit reached
        """
        self._load_all_files()
        sinks = self._scan_sinks()
        paths: list[DataFlowPath] = []

        for sink_info in sinks:
            if len(paths) >= max_paths:
                break

            func_name = sink_info["function"]
            file_path = sink_info["file"]
            sink_var = sink_info["sink_var"]
            rhs_vars = sink_info.get("rhs_vars", [sink_var])

            sink_node = TaintNode(
                variable=sink_info["lhs"],
                node_type="SINK",
                transform="",
                file=file_path,
                line=sink_info["line"],
                function=func_name,
            )

            for rhs_var in rhs_vars:
                visited: set[tuple[str, str]] = set()  # (func, var)
                chain = self._trace_backward(
                    rhs_var, func_name, file_path,
                    max_depth, visited,
                )
                if chain:
                    source_node = chain[0]
                    source_node.node_type = "SOURCE"
                    for step in chain[1:]:
                        step.node_type = "INTERMEDIATE"

                    path = DataFlowPath(
                        source=source_node,
                        sink=sink_node,
                        steps=chain[1:] if len(chain) > 1 else [],
                    )
                    paths.append(path)
                    if len(paths) >= max_paths:
                        break

        return paths

    def _load_all_files(self) -> None:
        """Parse all project files and cache assignments/calls."""
        files = self.repo.list_files(self.project_id)
        for f in files:
            rp = f["relative_path"]
            if not rp.endswith((".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")):
                continue

            path = f["path"]
            root = ts_parser.parse_file(path)
            if root is None:
                continue

            assignments = ts_parser.extract_all_assignments(root)
            calls = ts_parser.extract_call_arguments(root)
            params = ts_parser.extract_function_params(root)
            returns = ts_parser.extract_function_returns(root)

            self._file_assignments[rp] = assignments
            self._file_calls[rp] = calls
            self._file_params[rp] = params
            self._file_returns[rp] = returns

            for a in assignments:
                if a["function"]:
                    self._func_to_file[a["function"]] = rp
            for p in params:
                if p["function_name"]:
                    self._func_to_file[p["function_name"]] = rp

    def _scan_sinks(self) -> list[dict]:
        """Find all assignments whose LHS matches a sink pattern."""
        sinks = []
        for file_path, assignments in self._file_assignments.items():
            for a in assignments:
                lhs = a["lhs"]
                rhs = a["rhs"]
                full_text = f"{lhs} {a['operator']} {rhs}"

                for pattern in self._compiled_sinks:
                    if pattern.search(lhs) or pattern.search(full_text):
                        sinks.append({
                            "lhs": lhs,
                            "sink_var": rhs,
                            "rhs_vars": a["rhs_vars"],
                            "line": a["line"],
                            "function": a["function"],
                            "file": file_path,
                        })
                        break

            # also check for macro-style sinks in raw file content
            for file_path2, calls in self._file_calls.items():
                if file_path2 != file_path:
                    continue
                for call in calls:
                    callee = call["callee_name"]
                    for pattern in self._compiled_sinks:
                        call_text = f"{callee}({', '.join(a['expression'] for a in call['args'])})"
                        if pattern.search(call_text):
                            # the value being written is typically the last arg
                            rhs_args = call["args"]
                            rhs_vars = []
                            for arg in rhs_args:
                                rhs_vars.extend(
                                    ts_parser._extract_variables(
                                        ts_parser.parse_bytes(arg["expression"].encode())
                                    )
                                    if arg["expression"] else []
                                )
                            sinks.append({
                                "lhs": call_text[:100],
                                "sink_var": rhs_args[-1]["expression"] if rhs_args else "",
                                "rhs_vars": rhs_vars or [rhs_args[-1]["expression"]] if rhs_args else [],
                                "line": call["line"],
                                "function": call["function"],
                                "file": file_path,
                            })
                            break

        return sinks

    def _trace_backward(
        self,
        var: str,
        func_name: str,
        file_path: str,
        depth: int,
        visited: set[tuple[str, str]],
    ) -> list[TaintNode] | None:
        """Trace a variable backward to its source.

        Returns list of TaintNodes from source to current point, or None
        if no source was found within the depth limit.
        """
        if depth <= 0:
            return None

        key = (func_name, var)
        if key in visited:
            return None
        visited.add(key)

        # check if var matches a source pattern
        if self._match_source(var):
            # normalize separator: cfg.field → cfg->field for consistency
            source_var = var
            if "." in var and "->" not in var:
                source_var = var.replace(".", "->", 1)
            return [TaintNode(
                variable=source_var,
                node_type="SOURCE",
                file=file_path,
                line=0,
                function=func_name,
            )]

        # build reaching definitions for this function
        func_assignments = [
            a for a in self._file_assignments.get(file_path, [])
            if a["function"] == func_name
        ]

        # build alias map for this function
        alias_map = self._build_alias_map(func_assignments)

        # resolve the variable through aliases
        resolved_var = alias_map.resolve_field(var)
        if resolved_var != var and self._match_source(resolved_var):
            source_var = resolved_var
            if "." in resolved_var and "->" not in resolved_var:
                source_var = resolved_var.replace(".", "->", 1)
            return [TaintNode(
                variable=source_var,
                node_type="SOURCE",
                file=file_path,
                function=func_name,
            )]

        # find assignments where LHS matches our variable
        reaching = self._find_reaching_defs(resolved_var, func_assignments)

        for assign in reaching:
            # if RHS is a function call, dive into the callee's return values
            callee = assign.get("rhs_call")
            if callee and callee in self._func_to_file:
                callee_file = self._func_to_file[callee]
                for ret in self._file_returns.get(callee_file, []):
                    if ret["function"] != callee:
                        continue
                    for ret_var in ret["return_vars"]:
                        chain = self._trace_backward(
                            ret_var, callee, callee_file,
                            depth - 1, visited,
                        )
                        if chain:
                            chain.append(TaintNode(
                                variable=resolved_var,
                                node_type="INTERMEDIATE",
                                transform=f"={callee}(...)",
                                file=callee_file,
                                line=ret["line"],
                                function=callee,
                            ))
                            return chain

            # for each RHS variable, recurse
            for rhs_var in assign["rhs_vars"]:
                resolved_rhs = alias_map.resolve_field(rhs_var)
                chain = self._trace_backward(
                    resolved_rhs, func_name, file_path,
                    depth - 1, visited,
                )
                if chain:
                    chain.append(TaintNode(
                        variable=resolved_var,
                        node_type="INTERMEDIATE",
                        transform=assign["transform"] or "",
                        file=file_path,
                        line=assign["line"],
                        function=func_name,
                    ))
                    return chain

        # try tracing through function parameters (inter-procedural)
        if self._is_param(var, func_name, file_path):
            callers = self._find_callers_with_args(func_name, var)
            for caller_func, caller_file, arg_expr in callers:
                chain = self._trace_backward(
                    arg_expr, caller_func, caller_file,
                    depth - 1, visited,
                )
                if chain:
                    chain.append(TaintNode(
                        variable=f"{func_name}({var})",
                        node_type="INTERMEDIATE",
                        transform="param",
                        file=file_path,
                        function=func_name,
                    ))
                    return chain

            # fallback: cross-function struct field linking
            # if var is a param field (e.g. fw->timing_val), search all
            # functions for assignments to the same field name
            if not callers:
                writers = self._find_cross_func_field_writers(
                    var, func_name, file_path,
                )
                for writer_func, writer_file, writer_assign in writers:
                    for rhs_var in writer_assign["rhs_vars"]:
                        chain = self._trace_backward(
                            rhs_var, writer_func, writer_file,
                            depth - 1, visited,
                        )
                        if chain:
                            chain.append(TaintNode(
                                variable=var,
                                node_type="INTERMEDIATE",
                                transform=writer_assign["transform"] or "",
                                file=writer_file,
                                line=writer_assign["line"],
                                function=writer_func,
                            ))
                            return chain

        # fallback: cross-function plain variable (e.g. global variable)
        # if var has no reaching def and is not a parameter, search other
        # functions for assignments to the same variable name
        if not reaching and not self._is_param(var, func_name, file_path):
            if "->" not in var and "." not in var:
                writers = self._find_cross_func_var_writers(
                    var, func_name, file_path,
                )
                for writer_func, writer_file, writer_assign in writers:
                    for rhs_var in writer_assign["rhs_vars"]:
                        chain = self._trace_backward(
                            rhs_var, writer_func, writer_file,
                            depth - 1, visited,
                        )
                        if chain:
                            chain.append(TaintNode(
                                variable=var,
                                node_type="INTERMEDIATE",
                                transform="global",
                                file=writer_file,
                                line=writer_assign["line"],
                                function=writer_func,
                            ))
                            return chain

        return None

    def _build_alias_map(self, assignments: list[dict]) -> AliasMap:
        """Build pointer alias map from assignments in a function."""
        alias_map = AliasMap()
        for a in assignments:
            lhs = a["lhs"]
            rhs = a["rhs"]
            # detect pointer/address assignments: p = q, p = &obj
            # skip function call results — those are not pointer aliases
            if a.get("rhs_call"):
                continue
            if a["operator"] == "=" and "->" not in lhs and "." not in lhs:
                # simple variable assignment (likely pointer alias)
                if "->" not in rhs and "." not in rhs:
                    # skip numeric/string literals
                    if not re.match(r'^[\d"\']', rhs) and rhs not in ("NULL", "nullptr", "0"):
                        clean_rhs = rhs.lstrip("&*")
                        alias_map.add(lhs, clean_rhs)
        return alias_map

    def _find_reaching_defs(self, var: str, assignments: list[dict]) -> list[dict]:
        """Find assignments where LHS matches the target variable.

        Returns all matching definitions (not just the most recent) to handle
        phi-node patterns where if/else branches assign different values.
        """
        results = []
        seen_lines: set[int] = set()
        for a in reversed(assignments):
            lhs = a["lhs"]
            if lhs == var and a["line"] not in seen_lines:
                results.append(a)
                seen_lines.add(a["line"])
        return results

    def _match_source(self, variable: str) -> bool:
        """Check if a variable matches any source pattern.

        Also checks with '.' replaced by '->' (and vice versa) to handle
        struct copy patterns where value-type access uses '.' but source
        patterns expect '->'.
        """
        for pattern in self._compiled_sources:
            if pattern.search(variable):
                return True
        # try with separator swapped: cfg.field ↔ cfg->field
        if "." in variable and "->" not in variable:
            swapped = variable.replace(".", "->", 1)
            for pattern in self._compiled_sources:
                if pattern.search(swapped):
                    return True
        return False

    def _is_param(self, var: str, func_name: str, file_path: str) -> bool:
        """Check if var is a parameter of the given function."""
        for fp in self._file_params.get(file_path, []):
            if fp["function_name"] == func_name:
                for param in fp["params"]:
                    if param["name"] == var or var.startswith(param["name"] + "->") or var.startswith(param["name"] + "."):
                        return True
        return False

    def _find_callers_with_args(
        self, func_name: str, param_var: str,
    ) -> list[tuple[str, str, str]]:
        """Find callers that pass a value to the given parameter.

        Returns list of (caller_func, caller_file, arg_expression).
        """
        # find which parameter index corresponds to param_var
        param_index = None
        for file_path, params_list in self._file_params.items():
            for fp in params_list:
                if fp["function_name"] == func_name:
                    for param in fp["params"]:
                        # handle both direct match and field access
                        base_var = param_var.split("->")[0].split(".")[0]
                        if param["name"] == base_var:
                            param_index = param["index"]
                            break
                    break
            if param_index is not None:
                break

        if param_index is None:
            return []

        results = []
        for file_path, calls in self._file_calls.items():
            for call in calls:
                if call["callee_name"] == func_name:
                    for arg in call["args"]:
                        if arg["index"] == param_index:
                            # reconstruct the full field access if needed
                            arg_expr = arg["expression"]
                            if "->" in param_var:
                                suffix = param_var.split("->", 1)[1]
                                if "->" not in arg_expr and "." not in arg_expr:
                                    arg_expr = f"{arg_expr}->{suffix}"
                            results.append((
                                call["function"],
                                file_path,
                                arg_expr,
                            ))
        return results

    def _find_cross_func_field_writers(
        self, var: str, current_func: str, current_file: str,
    ) -> list[tuple[str, str, dict]]:
        """Find assignments in other functions that write to the same struct field.

        When a parameter field like `fw->timing_val` has no callers, search
        all functions for assignments whose LHS ends with the same field
        suffix (e.g. `->timing_val`).

        Returns list of (writer_func, writer_file, assignment_dict).
        """
        # extract field suffix: "fw->timing_val" → "->timing_val"
        for sep in ("->", "."):
            if sep in var:
                field_suffix = sep + var.split(sep, 1)[1]
                break
        else:
            return []

        results = []
        for file_path, assignments in self._file_assignments.items():
            for a in assignments:
                if a["function"] == current_func and file_path == current_file:
                    continue
                if a["lhs"].endswith(field_suffix):
                    results.append((a["function"], file_path, a))
        return results

    def _find_cross_func_var_writers(
        self, var: str, current_func: str, current_file: str,
    ) -> list[tuple[str, str, dict]]:
        """Find assignments in other functions that write to the same plain variable.

        Used for global variable tracking: when a variable has no local def
        and is not a parameter, search other functions for writes to the
        same variable name.

        Returns list of (writer_func, writer_file, assignment_dict).
        """
        results = []
        for file_path, assignments in self._file_assignments.items():
            for a in assignments:
                if a["function"] == current_func and file_path == current_file:
                    continue
                if a["lhs"] == var:
                    results.append((a["function"], file_path, a))
        return results

    def save_results(self, paths: list[DataFlowPath]) -> int:
        """Save analysis results to the database."""
        self.repo.delete_dataflow_paths(self.project_id)
        for path in paths:
            self.repo.insert_dataflow_path(
                self.project_id,
                source_var=path.source.variable,
                sink_var=path.sink.variable,
                path_json=json.dumps(path.to_dict()),
                depth=path.depth,
            )
        return len(paths)
