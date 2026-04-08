"""
CLI entry-point.  All user-facing commands live here.

Usage examples:
  cpp-analyzer index ./my_project --db analysis.db
  cpp-analyzer stats --db analysis.db
  cpp-analyzer query symbol "NetworkManager"
  cpp-analyzer query config "debug_mode"
  cpp-analyzer trace config "max_threads" --depth 5
  cpp-analyzer trace path "main" "processRequest"
  cpp-analyzer tree "processRequest" --direction up
  cpp-analyzer report --db analysis.db
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich import print as rprint

from ..core.indexer import Indexer
from ..db.repository import Repository
from ..analysis.config_tracker import ConfigTracker
from ..analysis.call_graph import CallGraph
from ..analysis.path_tracer import PathTracer, PathNode
from ..analysis.dependency_graph import DependencyGraph, FileNode

console = Console()

DEFAULT_DB = "cpp_analysis.db"


def _load_patterns(patterns_file: str | None) -> list[dict] | None:
    """Load config patterns from YAML; return None if file not found."""
    import yaml
    candidates = []
    if patterns_file:
        candidates.append(Path(patterns_file))
    # look for config_patterns.yaml next to the package root
    candidates += [
        Path(__file__).parents[3] / "config_patterns.yaml",
        Path.cwd() / "config_patterns.yaml",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f)
            return data.get("patterns", [])
    return None


def _get_repo(db: str) -> Repository:
    repo = Repository(db)
    repo.connect()
    return repo


def _resolve_project(repo: Repository, project_id: int | None) -> int:
    if project_id is not None:
        return project_id
    projects = repo.list_projects()
    if not projects:
        console.print("[red]No projects found. Run `index` first.[/red]")
        sys.exit(1)
    if len(projects) == 1:
        return projects[0]["id"]
    console.print("[yellow]Multiple projects found. Specify --project-id:[/yellow]")
    for p in projects:
        rp = p['root_path']
        display = ", ".join(json.loads(rp)) if rp.startswith("[") else rp
        console.print(f"  {p['id']:3d}  {p['name']}  ({display})")
    sys.exit(1)


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group()
@click.version_option("0.1.0")
def cli():
    """C++ code analysis framework — index, query, and trace configurations."""


# ── index ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("directories", nargs=-1, required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--db",           default=DEFAULT_DB,  show_default=True, help="SQLite DB path")
@click.option("--name",         default=None,        help="Project name (default: first directory name)")
@click.option("--patterns",     default=None,        help="config_patterns.yaml path")
@click.option("--force",        is_flag=True,        help="Re-index all files even if unchanged")
@click.option("--clang-args",   default="",          help="Extra clang args (comma-separated)")
def index(directories, db, name, patterns, force, clang_args):
    """Parse and index one or more C++ source directories."""
    roots = [Path(d).resolve() for d in directories]
    project_name = name or roots[0].name

    repo = _get_repo(db)
    project_id = repo.upsert_project(project_name, [str(r) for r in roots])

    console.print(f"[bold]Project:[/bold] {project_name}  ({len(roots)} director{'y' if len(roots) == 1 else 'ies'})")
    for r in roots:
        console.print(f"  [dim]{r}[/dim]")

    # load and sync config patterns
    pattern_list = _load_patterns(patterns)
    if pattern_list:
        repo.sync_config_patterns(pattern_list)
        console.print(f"[cyan]Loaded {len(pattern_list)} config patterns[/cyan]")
    else:
        console.print("[yellow]No config_patterns.yaml found; config tracking skipped.[/yellow]")

    extra_args = [a.strip() for a in clang_args.split(",") if a.strip()]

    with console.status("[bold green]Indexing...") as status:
        def progress(path, i, total):
            status.update(f"[bold green]Indexing {i}/{total}: {Path(path).name}")

        indexer = Indexer(repo, project_id, roots, extra_args or None, progress)
        stats = indexer.run(force=force)

    console.print(f"[bold green]Indexing complete[/bold green]")
    console.print(f"  Indexed : {stats.indexed} files")
    console.print(f"  Skipped : {stats.skipped} (unchanged)")
    console.print(f"  Fallback: {stats.fallback} (regex parser)")
    console.print(f"  Symbols : {stats.symbols}")
    console.print(f"  Calls   : {stats.calls}")

    if stats.parse_errors:
        console.print(f"\n[yellow]Parse errors in {len(stats.parse_errors)} files:[/yellow]")
        for fn, errs in stats.parse_errors[:5]:
            console.print(f"  {fn}: {errs[0]}")

    # run config scan after indexing
    if pattern_list:
        console.print("\n[cyan]Scanning for config usages...[/cyan]")
        tracker = ConfigTracker(repo, project_id)
        total_hits = tracker.scan_all()
        console.print(f"  Config hits: {total_hits}")

    repo.close()


# ── stats ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
def stats(db, project_id):
    """Show database statistics."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    p = repo.get_project(pid)
    s = repo.stats(pid)

    table = Table(title=f"Project: {p['name']}", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for k, v in s.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)
    repo.close()


# ── query group ───────────────────────────────────────────────────────────────

@cli.group()
def query():
    """Query indexed symbols and config keys."""


@query.command("symbol")
@click.argument("name")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--kind",       default=None, help="Filter by kind: FUNCTION, CLASS, METHOD …")
@click.option("--limit",      default=30, show_default=True)
def query_symbol(name, db, project_id, kind, limit):
    """Search for symbols by name."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    rows = repo.search_symbols(name, project_id=pid, kind=kind, limit=limit)

    table = Table(title=f"Symbols matching '{name}'")
    table.add_column("ID",            style="dim",  width=6)
    table.add_column("Kind",          style="cyan", width=16)
    table.add_column("Qualified Name",style="bold white")
    table.add_column("File",          style="blue")
    table.add_column("Line",          justify="right", width=6)

    for r in rows:
        table.add_row(
            str(r["id"]),
            r["kind"],
            r["qualified_name"] or r["name"],
            r["relative_path"],
            str(r["line_start"] or ""),
        )
    console.print(table)
    repo.close()


@query.command("config")
@click.argument("key", required=False, default=None)
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--list",       "list_all", is_flag=True, help="List all known config keys")
def query_config(key, db, project_id, list_all):
    """Show config key usages.  Without KEY, lists all known keys."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)

    if list_all or key is None:
        rows = repo.list_config_keys(pid)
        table = Table(title="Config Keys")
        table.add_column("Key",          style="bold yellow")
        table.add_column("Type",         style="cyan", width=16)
        table.add_column("Source Count", justify="right")
        for r in rows:
            table.add_row(r["config_key"], r["pattern_type"], str(r["source_count"]))
        console.print(table)
    else:
        # show all usages of the key
        sources  = repo.get_config_sources(pid, key)
        usages   = repo.get_config_usages(pid, key)

        if not sources and not usages:
            console.print(f"[yellow]No occurrences of config key '{key}' found.[/yellow]")
            repo.close()
            return

        # Sources table
        t1 = Table(title=f"Config Sources: '{key}'")
        t1.add_column("File",     style="blue")
        t1.add_column("Line",     justify="right", width=6)
        t1.add_column("Pattern",  style="cyan", width=14)
        t1.add_column("Fn",       style="green")
        t1.add_column("Snippet",  style="dim")
        for r in sources:
            t1.add_row(
                r["relative_path"], str(r["line"]),
                r["pattern_name"] or "",
                (r["enclosing_fn"] or "")[:50],
                (r["code_snippet"] or "").strip()[:60],
            )
        console.print(t1)

        # Usages table
        t2 = Table(title=f"Config Usages: '{key}'")
        t2.add_column("File",     style="blue")
        t2.add_column("Line",     justify="right", width=6)
        t2.add_column("Type",     style="cyan", width=12)
        t2.add_column("CF?",      style="yellow", width=4)
        t2.add_column("Function", style="green")
        t2.add_column("Snippet",  style="dim")
        for r in usages:
            t2.add_row(
                r["relative_path"], str(r["line"]),
                r["usage_type"] or "",
                "Y" if r["affects_control_flow"] else "",
                (r["fn_name"] or "")[:50],
                (r["code_snippet"] or "").strip()[:60],
            )
        console.print(t2)

    repo.close()


# ── trace group ───────────────────────────────────────────────────────────────

@cli.group()
def trace():
    """Trace code paths: config→functions or function→function."""


@trace.command("config")
@click.argument("key")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--depth",      default=5, show_default=True, help="Max call depth")
@click.option("--chains",     default=20, show_default=True, help="Max call chains")
def trace_config(key, db, project_id, depth, chains):
    """Trace all code paths activated by a config key."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)

    cg = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    result = tracer.trace_config(key, max_depth=depth, max_chains=chains)

    console.print(f"\n[bold yellow]Config key:[/bold yellow] {key}")
    console.print(f"  Direct functions   : {result.stats['direct_functions']}")
    console.print(f"  Affected functions : {result.stats['affected_functions']}")
    console.print(f"  Call chains found  : {result.stats['call_chains']}")

    # Direct functions
    if result.source_nodes:
        t = Table(title="Functions that directly read this config")
        t.add_column("Function", style="bold green")
        t.add_column("File",     style="blue")
        t.add_column("Line",     justify="right")
        for n in result.source_nodes:
            t.add_row(n.qualified_name, n.file, str(n.line))
        console.print(t)

    # Call chains
    if result.call_chains:
        console.print(f"\n[bold]Call chains (max {chains}):[/bold]")
        for i, chain in enumerate(result.call_chains, 1):
            parts = " → ".join(n.qualified_name for n in chain)
            console.print(f"  {i:2d}. {parts}")

    repo.close()


@trace.command("dataflow")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--source",     default=None, help="Source pattern regex (default: config field patterns)")
@click.option("--sink",       default=None, help="Sink pattern regex (default: REG_WRITE, reg->field patterns)")
@click.option("--depth",      default=5, show_default=True, help="Max trace depth")
@click.option("--max-paths",  default=100, show_default=True, help="Max dataflow paths")
@click.option("--save",       is_flag=True, help="Save results to DB")
@click.option("--format",     "fmt", default="tree", type=click.Choice(["tree", "json"]),
              show_default=True, help="Output format")
def trace_dataflow(db, project_id, source, sink, depth, max_paths, save, fmt):
    """Trace dataflow from config fields to register writes (taint analysis)."""
    from ..analysis.taint_tracker import TaintTracker, DEFAULT_SOURCE_PATTERNS, DEFAULT_SINK_PATTERNS

    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)

    source_patterns = DEFAULT_SOURCE_PATTERNS
    if source:
        source_patterns = [{"name": "custom", "regex": source}]

    sink_patterns = DEFAULT_SINK_PATTERNS
    if sink:
        sink_patterns = [{"name": "custom", "regex": sink}]

    with console.status("[bold green]Running taint analysis..."):
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        paths = tracker.trace(max_depth=depth, max_paths=max_paths)

    if save and paths:
        count = tracker.save_results(paths)
        console.print(f"[cyan]Saved {count} dataflow paths to DB[/cyan]")

    if not paths:
        console.print("[yellow]No dataflow paths found.[/yellow]")
        repo.close()
        return

    console.print(f"\n[bold]Found {len(paths)} dataflow path(s)[/bold]\n")

    if fmt == "json":
        import json as _json
        console.print(_json.dumps([p.to_dict() for p in paths], indent=2))
    else:
        for i, path in enumerate(paths, 1):
            tree = Tree(f"[bold yellow]Path {i}[/bold yellow]: {path.source.variable} → {path.sink.variable}")
            nodes = [path.source] + path.steps + [path.sink]
            for j, node in enumerate(nodes):
                style = {"SOURCE": "bold green", "SINK": "bold red"}.get(node.node_type, "cyan")
                label = f"[{style}]{node.variable}[/{style}]"
                if node.transform:
                    label += f"  [dim]({node.transform})[/dim]"
                if node.file:
                    label += f"  [blue]{node.file}:{node.line}[/blue]"
                if node.function:
                    label += f"  [dim]{node.function}()[/dim]"
                tree.add(label)
            console.print(tree)
            console.print()

    repo.close()


@trace.command("path")
@click.argument("source")
@click.argument("target")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--max-paths",  default=10, show_default=True)
def trace_path(source, target, db, project_id, max_paths):
    """Find all call paths between SOURCE and TARGET functions."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)

    cg = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    paths = tracer.trace_path(source, target, max_paths=max_paths)

    if not paths:
        console.print(f"[yellow]No call path found from '{source}' to '{target}'.[/yellow]")
    else:
        console.print(f"\n[bold]Call paths from '{source}' to '{target}':[/bold]")
        for i, path in enumerate(paths, 1):
            parts = " → ".join(n.qualified_name for n in path)
            console.print(f"  {i:2d}. {parts}")

    repo.close()


# ── tree ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("function_name")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--direction",  default="down", type=click.Choice(["up", "down"]),
              show_default=True, help="down=callees, up=callers")
@click.option("--depth",      default=4, show_default=True)
def tree(function_name, db, project_id, direction, depth):
    """Display a call tree rooted at FUNCTION_NAME."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)

    cg = CallGraph(repo, pid)
    cg.build()
    tracer = PathTracer(repo, cg, pid)
    root = tracer.call_tree(function_name, direction=direction, max_depth=depth)

    if root is None:
        console.print(f"[yellow]Function '{function_name}' not found.[/yellow]")
        repo.close()
        return

    label = "callee" if direction == "down" else "caller"
    rich_tree = Tree(
        f"[bold green]{root.qualified_name}[/bold green]"
        f" [dim]{root.file}:{root.line}[/dim]"
    )
    _render_tree_node(root, rich_tree, label)
    console.print(rich_tree)
    repo.close()


def _render_tree_node(node: PathNode, rich_parent, label: str):
    for child in node.children:
        branch = rich_parent.add(
            f"[cyan]{child.qualified_name}[/cyan]"
            f" [dim]{child.file}:{child.line}[/dim]"
        )
        _render_tree_node(child, branch, label)


# ── report ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--output",     default=None, help="Write report to file (markdown)")
def report(db, project_id, output):
    """Generate a comprehensive analysis report."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    p   = repo.get_project(pid)
    s   = repo.stats(pid)

    rp = p['root_path']
    root_display = ", ".join(json.loads(rp)) if rp.startswith("[") else rp

    lines = [
        f"# C++ Analysis Report: {p['name']}",
        f"\nRoot: `{root_display}`  |  Last indexed: {p['last_indexed']}",
        "\n## Summary\n",
    ]
    for k, v in s.items():
        lines.append(f"- **{k.replace('_',' ').title()}**: {v}")

    # Config keys section
    keys = repo.list_config_keys(pid)
    if keys:
        lines.append("\n## Configuration Keys\n")
        lines.append("| Key | Type | Sources |")
        lines.append("|-----|------|---------|")
        for r in keys:
            lines.append(f"| `{r['config_key']}` | {r['pattern_type']} | {r['source_count']} |")

    # Top callers
    cg = CallGraph(repo, pid)
    cg.build()
    lines.append("\n## Most-Called Functions\n")
    lines.append("| Function | Times Called |")
    lines.append("|----------|-------------|")
    for sym_id, in_deg in cg.top_callers(15):
        sym = repo.get_symbol(sym_id)
        if sym:
            lines.append(f"| `{sym['qualified_name'] or sym['name']}` | {in_deg} |")

    text = "\n".join(lines)

    if output:
        Path(output).write_text(text)
        console.print(f"[green]Report written to {output}[/green]")
    else:
        console.print(text)

    repo.close()


# ── callers / callees ─────────────────────────────────────────────────────────

@cli.command()
@click.argument("function_name")
@click.option("--db",         default=DEFAULT_DB, show_default=True)
@click.option("--project-id", default=None, type=int)
@click.option("--direction",  default="callers",
              type=click.Choice(["callers", "callees"]), show_default=True)
@click.option("--depth",      default=1, show_default=True)
def who(function_name, db, project_id, direction, depth):
    """Show callers or callees of a function."""
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    cg = CallGraph(repo, pid)
    cg.build()

    ids = []
    rows = repo.search_symbols(function_name, project_id=pid, limit=5)
    if not rows:
        console.print(f"[yellow]No function matching '{function_name}'[/yellow]")
        repo.close()
        return
    sym_id = rows[0]["id"]

    if direction == "callers":
        ids = cg.callers_of(sym_id, depth=depth)
        title = f"Callers of '{function_name}' (depth={depth})"
    else:
        ids = cg.callees_of(sym_id, depth=depth)
        title = f"Callees of '{function_name}' (depth={depth})"

    t = Table(title=title)
    t.add_column("Function", style="cyan")
    t.add_column("File",     style="blue")
    t.add_column("Line",     justify="right")
    for sid in ids:
        sym = repo.get_symbol(sid)
        if sym:
            t.add_row(sym["qualified_name"] or sym["name"],
                      sym["relative_path"], str(sym["line_start"] or ""))
    console.print(t)
    repo.close()


# ── deps ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("file_path", required=False, default=None)
@click.option("--db",           default=DEFAULT_DB, show_default=True)
@click.option("--project-id",   default=None, type=int)
@click.option("--direction",    default="includes",
              type=click.Choice(["includes", "included-by"]), show_default=True,
              help="includes = what this file includes; included-by = who includes it")
@click.option("--depth",        default=3, show_default=True)
@click.option("--circular",     is_flag=True, help="Detect circular dependencies")
@click.option("--top",          default=None, type=int,
              help="Show top N most-included and most-including files")
@click.option("--show-system",  is_flag=True, help="Include system headers")
def deps(file_path, db, project_id, direction, depth, circular, top, show_system):
    """Show file dependency (include) relationships.

    Without FILE_PATH, use --circular or --top for project-wide analysis.
    With FILE_PATH, display the include tree rooted at that file.
    """
    repo = _get_repo(db)
    pid = _resolve_project(repo, project_id)
    dg = DependencyGraph(repo, pid)
    dg.build(include_system=show_system)

    if circular:
        cycles = dg.circular_dependencies()
        if not cycles:
            console.print("[green]No circular dependencies found.[/green]")
        else:
            table = Table(title=f"Circular Dependencies ({len(cycles)} cycles)")
            table.add_column("#",     style="dim", width=5, justify="right")
            table.add_column("Cycle", style="bold red")
            for i, cycle in enumerate(cycles, 1):
                parts = []
                for fid in cycle:
                    f = repo.get_file(fid)
                    parts.append(f["relative_path"] if f else f"<id:{fid}>")
                parts.append(parts[0])  # close the cycle visually
                table.add_row(str(i), " -> ".join(parts))
            console.print(table)
        repo.close()
        return

    if top is not None:
        n = top if top > 0 else 15
        # Most included files
        t1 = Table(title=f"Top {n} Most Included Files")
        t1.add_column("#",          style="dim", width=5, justify="right")
        t1.add_column("File",       style="cyan")
        t1.add_column("Included By", justify="right", style="green")
        for i, (fid, count) in enumerate(dg.top_included(n), 1):
            f = repo.get_file(fid)
            t1.add_row(str(i), f["relative_path"] if f else f"<id:{fid}>", str(count))
        console.print(t1)

        # Most including files
        t2 = Table(title=f"Top {n} Files With Most Includes")
        t2.add_column("#",        style="dim", width=5, justify="right")
        t2.add_column("File",     style="cyan")
        t2.add_column("Includes", justify="right", style="green")
        for i, (fid, count) in enumerate(dg.top_includers(n), 1):
            f = repo.get_file(fid)
            t2.add_row(str(i), f["relative_path"] if f else f"<id:{fid}>", str(count))
        console.print(t2)

        console.print(f"\n[dim]Graph: {dg.node_count()} files, {dg.edge_count()} include edges[/dim]")
        repo.close()
        return

    if file_path is None:
        console.print("[yellow]Specify FILE_PATH, or use --circular / --top.[/yellow]")
        repo.close()
        return

    # Find the file
    files = repo.get_file_by_path(pid, file_path)
    if not files:
        console.print(f"[yellow]No file matching '{file_path}' found.[/yellow]")
        repo.close()
        return
    target = files[0]
    fid = target["id"]

    root = dg.build_tree(fid, direction=direction, max_depth=depth)
    if root is None:
        console.print(f"[yellow]File '{file_path}' not in dependency graph.[/yellow]")
        repo.close()
        return

    label = "includes" if direction == "includes" else "included by"
    rich_tree = Tree(
        f"[bold green]{root.relative_path}[/bold green]"
        f" [dim]({label}, depth={depth})[/dim]"
    )
    _render_dep_tree_node(root, rich_tree)
    console.print(rich_tree)
    repo.close()


def _render_dep_tree_node(node: FileNode, rich_parent):
    for child in node.children:
        branch = rich_parent.add(
            f"[cyan]{child.relative_path}[/cyan]"
        )
        _render_dep_tree_node(child, branch)
