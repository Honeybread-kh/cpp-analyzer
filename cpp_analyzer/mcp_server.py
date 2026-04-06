"""
MCP Server for cpp-analyzer.

Exposes the analysis capabilities as MCP tools so Claude (or any MCP client)
can index C++ projects and query them conversationally.

Run:
    cpp-analyzer-mcp                          # stdio transport (for Claude Desktop)
    uv run cpp-analyzer-mcp                   # via uv

Add to Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "cpp-analyzer": {
          "command": "uv",
          "args": ["--directory", "/path/to/cpp_analyzer", "run", "cpp-analyzer-mcp"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .core.indexer import Indexer
from .db.repository import Repository
from .analysis.config_tracker import ConfigTracker
from .analysis.call_graph import CallGraph
from .analysis.path_tracer import PathTracer

mcp = FastMCP(
    "cpp-analyzer",
    instructions=(
        "C++ static analysis tool. "
        "Use `index_project` first to parse a codebase into a DB, "
        "then use query/trace tools to explore symbols and config usage."
    ),
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _default_db(db_path: str | None) -> str:
    return db_path or os.environ.get("CPP_ANALYZER_DB", "cpp_analysis.db")


def _patterns_path() -> str | None:
    candidates = [
        Path(__file__).parents[1] / "config_patterns.yaml",
        Path.cwd() / "config_patterns.yaml",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _load_patterns(patterns_file: str | None = None) -> list[dict]:
    import yaml
    candidates = []
    if patterns_file:
        candidates.append(Path(patterns_file))
    candidates += [
        Path(__file__).parents[1] / "config_patterns.yaml",
        Path.cwd() / "config_patterns.yaml",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f).get("patterns", [])
    return []


def _repo(db_path: str) -> Repository:
    repo = Repository(db_path)
    repo.connect()
    return repo


def _resolve_project_id(repo: Repository, project_id: int | None) -> int | None:
    if project_id is not None:
        return project_id
    projects = repo.list_projects()
    return projects[0]["id"] if projects else None


# ── tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def index_project(
    directory: str,
    db_path: str | None = None,
    project_name: str | None = None,
    force: bool = False,
) -> str:
    """
    Parse and index a C++ source directory into the analysis database.
    Must be called before any other tool.

    Args:
        directory:    Absolute or relative path to the C++ source root.
        db_path:      SQLite DB file path (default: cpp_analysis.db in cwd).
        project_name: Human-readable project name (default: directory name).
        force:        Re-index all files even if unchanged.

    Returns:
        Summary of indexed files, symbols, calls, and config hits.
    """
    db = _default_db(db_path)
    root = Path(directory).resolve()
    if not root.exists():
        return f"ERROR: directory not found: {directory}"

    name = project_name or root.name
    repo = _repo(db)
    pid  = repo.upsert_project(name, str(root))

    patterns = _load_patterns()
    if patterns:
        repo.sync_config_patterns(patterns)

    indexer = Indexer(repo, pid, root)
    stats   = indexer.run(force=force)

    config_hits = 0
    if patterns:
        tracker     = ConfigTracker(repo, pid)
        config_hits = tracker.scan_all()

    repo.close()

    lines = [
        f"Indexed project '{name}' → {db}",
        f"  Files   indexed : {stats.indexed}",
        f"  Files   skipped : {stats.skipped} (unchanged)",
        f"  Symbols found   : {stats.symbols}",
        f"  Call edges      : {stats.calls}",
        f"  Config hits     : {config_hits}",
    ]
    if stats.parse_errors:
        lines.append(f"  Parse errors    : {len(stats.parse_errors)} files")
    return "\n".join(lines)


@mcp.tool()
def get_stats(db_path: str | None = None, project_id: int | None = None) -> str:
    """
    Return statistics for the indexed project (file count, symbol count, etc.).
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."

    p = repo.get_project(pid)
    s = repo.stats(pid)
    repo.close()

    lines = [f"Project: {p['name']}  (last indexed: {p['last_indexed']})"]
    for k, v in s.items():
        lines.append(f"  {k.replace('_',' ').title():<22}: {v}")
    return "\n".join(lines)


@mcp.tool()
def list_config_keys(
    db_path: str | None = None,
    project_id: int | None = None,
) -> str:
    """
    List all configuration keys detected in the codebase with their types and usage counts.
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."

    rows = repo.list_config_keys(pid)
    repo.close()

    if not rows:
        return "No config keys found."

    lines = [f"{'Key':<30} {'Type':<18} {'Sources':>7}"]
    lines.append("-" * 58)
    for r in rows:
        lines.append(f"{r['config_key']:<30} {r['pattern_type']:<18} {r['source_count']:>7}")
    return "\n".join(lines)


@mcp.tool()
def query_config(
    config_key: str,
    db_path: str | None = None,
    project_id: int | None = None,
) -> str:
    """
    Show all locations where a config key is read and how it affects control flow.

    Args:
        config_key: The config key name (e.g. "DEBUG_MODE", "max_threads").
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."

    sources = repo.get_config_sources(pid, config_key)
    usages  = repo.get_config_usages(pid, config_key)
    repo.close()

    if not sources and not usages:
        return f"Config key '{config_key}' not found in the indexed project."

    lines = [f"Config key: '{config_key}'", ""]
    lines.append("SOURCES (where this key is read):")
    for r in sources:
        fn = r["enclosing_fn"] or "<global>"
        lines.append(f"  {r['relative_path']}:{r['line']}  fn={fn}")
        lines.append(f"    {r['code_snippet'].strip()}")

    lines.append("")
    lines.append("USAGES (how it affects code):")
    for r in usages:
        cf   = " [CONTROL FLOW]" if r["affects_control_flow"] else ""
        fn   = r["fn_name"] or "<global>"
        lines.append(f"  {r['relative_path']}:{r['line']}  type={r['usage_type']}{cf}  fn={fn}")
        lines.append(f"    {r['code_snippet'].strip()}")

    return "\n".join(lines)


@mcp.tool()
def trace_config(
    config_key: str,
    db_path: str | None = None,
    project_id: int | None = None,
    max_depth: int = 5,
    max_chains: int = 20,
) -> str:
    """
    Trace all call chains that are transitively activated by a config key.
    Shows which functions execute when this config is set.

    Args:
        config_key: The config key to trace (e.g. "debug_mode").
        max_depth:  Maximum call chain depth (default 5).
        max_chains: Maximum number of chains to return (default 20).
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."

    cg     = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    result = tracer.trace_config(config_key, max_depth=max_depth, max_chains=max_chains)
    repo.close()

    if not result.source_nodes:
        return f"No functions found that read config key '{config_key}'."

    lines = [
        f"Config key: '{config_key}'",
        f"  Direct functions   : {result.stats['direct_functions']}",
        f"  Affected functions : {result.stats['affected_functions']}",
        "",
        "Functions that directly read this config:",
    ]
    for n in result.source_nodes:
        lines.append(f"  {n.qualified_name}  ({n.file}:{n.line})")

    if result.call_chains:
        lines.append("\nCall chains:")
        for i, chain in enumerate(result.call_chains, 1):
            parts = " → ".join(n.qualified_name for n in chain)
            lines.append(f"  {i:2d}. {parts}")

    return "\n".join(lines)


@mcp.tool()
def trace_path(
    source_function: str,
    target_function: str,
    db_path: str | None = None,
    project_id: int | None = None,
    max_paths: int = 10,
) -> str:
    """
    Find all call paths between two functions.

    Args:
        source_function: Starting function name.
        target_function: Destination function name.
        max_paths:       Maximum number of paths to return.
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."

    cg     = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    paths  = tracer.trace_path(source_function, target_function, max_paths=max_paths)
    repo.close()

    if not paths:
        return f"No call path found from '{source_function}' to '{target_function}'."

    lines = [f"Call paths from '{source_function}' → '{target_function}':"]
    for i, path in enumerate(paths, 1):
        parts = " → ".join(n.qualified_name for n in path)
        lines.append(f"  {i:2d}. {parts}")
    return "\n".join(lines)


@mcp.tool()
def call_tree(
    function_name: str,
    direction: str = "down",
    db_path: str | None = None,
    project_id: int | None = None,
    max_depth: int = 4,
) -> str:
    """
    Show the call tree rooted at a function.

    Args:
        function_name: Function to root the tree at.
        direction:     'down' = what this function calls; 'up' = who calls this function.
        max_depth:     Tree depth (default 4).
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."

    cg     = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    root   = tracer.call_tree(function_name, direction=direction, max_depth=max_depth)
    repo.close()

    if root is None:
        return f"Function '{function_name}' not found."

    lines: list[str] = []
    def render(node, prefix="", is_last=True):
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{node.qualified_name}  ({node.file}:{node.line})")
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(node.children):
            render(child, child_prefix, i == len(node.children) - 1)

    lines.append(f"{root.qualified_name}  ({root.file}:{root.line})")
    for i, child in enumerate(root.children):
        render(child, "", i == len(root.children) - 1)
    return "\n".join(lines)


@mcp.tool()
def search_symbols(
    query: str,
    kind: str | None = None,
    db_path: str | None = None,
    project_id: int | None = None,
    limit: int = 20,
) -> str:
    """
    Search for symbols (functions, classes, methods, variables) by name.

    Args:
        query: Partial or full symbol name.
        kind:  Optional filter: FUNCTION, METHOD, CLASS, STRUCT, VARIABLE, ENUM …
        limit: Max results (default 20).
    """
    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found."

    rows = repo.search_symbols(query, project_id=pid, kind=kind, limit=limit)
    repo.close()

    if not rows:
        return f"No symbols matching '{query}'."

    lines = [f"{'ID':>5}  {'Kind':<18}  {'Qualified Name':<50}  {'File'}"]
    lines.append("-" * 100)
    for r in rows:
        lines.append(
            f"{r['id']:>5}  {r['kind']:<18}  "
            f"{(r['qualified_name'] or r['name']):<50}  "
            f"{r['relative_path']}:{r['line_start'] or ''}"
        )
    return "\n".join(lines)


# ── config dependency analysis tools ─────────────────────────────────────────

@mcp.tool()
def analyze_configs(
    db_path: str | None = None,
    project_id: int | None = None,
    target_structs: str | None = None,
    output_dir: str | None = None,
    output_format: str = "all",
) -> str:
    """
    Analyze C++ config parameters, their dependencies, and forced overrides.
    Extracts struct fields, CLI argument mappings, default values,
    and inter-config dependencies (overrides, cascades, mutual exclusions).

    Outputs CSV files and/or KConfig description.

    Args:
        db_path:        SQLite DB path (default: cpp_analysis.db).
        project_id:     Project ID (default: first project).
        target_structs: Comma-separated struct names to analyze (default: auto-detect all).
        output_dir:     Directory for CSV/KConfig output (default: ./config_analysis/).
        output_format:  "csv", "kconfig", or "all" (default: "all").

    Returns:
        Summary of analysis and paths to generated files.
    """
    from .analysis.config_dependency import ConfigDependencyAnalyzer
    from .analysis.csv_exporter import export_csv, export_kconfig, generate_kconfig

    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."

    project = repo.get_project(pid)
    project_name = project["name"] if project else "unknown"

    structs = [s.strip() for s in target_structs.split(",")] if target_structs else []

    analyzer = ConfigDependencyAnalyzer(repo, pid, target_structs=structs)
    result = analyzer.analyze()
    repo.close()

    default_out = str(Path(__file__).parents[1] / "output" / project_name)
    out = output_dir or default_out

    lines = [
        f"Config Analysis for '{project_name}'",
        f"  Configs found      : {len(result.configs)}",
        f"  Dependencies found : {len(result.dependencies)}",
        "",
    ]

    # count by type
    by_type: dict[str, int] = {}
    for d in result.dependencies:
        by_type[d.relationship_type] = by_type.get(d.relationship_type, 0) + 1
    if by_type:
        lines.append("  Dependency breakdown:")
        for t, count in sorted(by_type.items()):
            lines.append(f"    {t:<25}: {count}")
        lines.append("")

    if output_format in ("csv", "all"):
        paths = export_csv(result.configs, result.dependencies, out)
        for name, path in paths.items():
            lines.append(f"  Written: {path}")

    if output_format in ("kconfig", "all"):
        kpath = export_kconfig(result.configs, result.dependencies, out, project_name)
        lines.append(f"  Written: {kpath}")

    # also include a short preview
    if result.configs:
        lines.append("")
        lines.append("Top configs (first 10):")
        for cfg in result.configs[:10]:
            flag = f" (cli: {cfg.cli_flag})" if cfg.cli_flag else ""
            default = f" = {cfg.default_value}" if cfg.default_value else ""
            lines.append(f"  {cfg.qualified_name}{default}{flag}")

    if result.dependencies:
        lines.append("")
        lines.append("Sample dependencies (first 10):")
        for dep in result.dependencies[:10]:
            lines.append(
                f"  [{dep.relationship_type}] {dep.source_config} "
                f"{dep.source_condition} → {dep.target_config} = {dep.forced_value}"
            )

    return "\n".join(lines)


@mcp.tool()
def export_configs_csv(
    db_path: str | None = None,
    project_id: int | None = None,
    target_structs: str | None = None,
) -> str:
    """
    Run config analysis and return results as inline CSV text.
    Useful when you want the raw data without writing files.

    Args:
        db_path:        SQLite DB path.
        project_id:     Project ID.
        target_structs: Comma-separated struct names to analyze.
    """
    from .analysis.config_dependency import ConfigDependencyAnalyzer
    from .analysis.csv_exporter import export_csv_string

    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."

    structs = [s.strip() for s in target_structs.split(",")] if target_structs else []
    analyzer = ConfigDependencyAnalyzer(repo, pid, target_structs=structs)
    result = analyzer.analyze()
    repo.close()

    return export_csv_string(result.configs, result.dependencies)


@mcp.tool()
def export_configs_kconfig(
    db_path: str | None = None,
    project_id: int | None = None,
    target_structs: str | None = None,
) -> str:
    """
    Run config analysis and return results as KConfig format text.
    KConfig is the Linux Kernel configuration language, ideal for
    expressing config dependencies (depends on, select, range, default).

    Args:
        db_path:        SQLite DB path.
        project_id:     Project ID.
        target_structs: Comma-separated struct names to analyze.
    """
    from .analysis.config_dependency import ConfigDependencyAnalyzer
    from .analysis.csv_exporter import generate_kconfig

    db   = _default_db(db_path)
    repo = _repo(db)
    pid  = _resolve_project_id(repo, project_id)
    if pid is None:
        repo.close()
        return "No project found. Run index_project first."

    project = repo.get_project(pid)
    project_name = project["name"] if project else "unknown"

    structs = [s.strip() for s in target_structs.split(",")] if target_structs else []
    analyzer = ConfigDependencyAnalyzer(repo, pid, target_structs=structs)
    result = analyzer.analyze()
    repo.close()

    return generate_kconfig(result.configs, result.dependencies, project_name)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
