# CLAUDE.md — cpp-analyzer

Guidance for AI assistants working on this repository.

---

## What this project does

`cpp-analyzer` is a Python-based **static analysis framework for C++ codebases**. It:

1. **Indexes** a C++ source tree using libclang (with a regex fallback) and stores everything in a local SQLite database.
2. **Tracks configuration keys** — env vars, map lookups, gflags, CLI args, JSON/YAML accessors, preprocessor defines — by matching patterns from `config_patterns.yaml`.
3. **Exposes query and trace commands** via a CLI (`cpp-analyzer`) and an MCP server (`cpp-analyzer-mcp`) so both humans and AI assistants can explore symbols, call graphs, and config usage conversationally.

---

## Repository layout

```
cpp-analyzer/
├── config_patterns.yaml          # Regex pattern definitions for config key detection
├── pyproject.toml                # Project metadata, dependencies, entry points (hatchling)
├── setup.py                      # Legacy setuptools shim (mirrors pyproject.toml)
├── requirements.txt              # Runtime deps without mcp (for pip-only installs)
├── examples/
│   └── sample.cpp                # Demo C++ file covering most config patterns
└── cpp_analyzer/
    ├── __init__.py               # Version: 0.1.0
    ├── __main__.py               # `python -m cpp_analyzer` entry point
    ├── mcp_server.py             # MCP server (FastMCP); exposes all tools over stdio
    ├── cli/
    │   └── commands.py           # Click CLI: index, stats, query, trace, tree, who, report
    ├── core/
    │   ├── ast_parser.py         # ClangParser (libclang) + regex fallback; produces ParseResult
    │   └── indexer.py            # Walks directory, calls parser, writes to DB (incremental)
    ├── analysis/
    │   ├── call_graph.py         # Builds a networkx DiGraph from DB call edges; graph queries
    │   ├── config_tracker.py     # Scans source lines against compiled patterns; writes config_sources/usages
    │   └── path_tracer.py        # PathTracer: config→function traces, A→B path finding, call trees
    └── db/
        ├── schema.py             # DDL (SQLite, schema v3, WAL mode)
        └── repository.py         # Repository class — all SQL; rest of code only touches this
```

---

## Architecture

```
CLI / MCP Server
      │
      ▼
   Indexer  ──────────────►  ClangParser (libclang or regex fallback)
      │                             │
      │  ParseResult                │ SymbolInfo, CallInfo, IncludeInfo
      ▼                             │
  Repository  ◄────────────────────┘
  (SQLite DB)
      │
      ├──► ConfigTracker   (pattern scan → config_sources, config_usages)
      │
      ├──► CallGraph       (networkx DiGraph from calls table)
      │
      └──► PathTracer      (trace_config, trace_path, call_tree)
```

### Key data flows

- **Indexing**: `Indexer.run()` collects `.cpp/.h/…` files, skips unchanged ones (SHA-256 hash), calls `ClangParser.parse_file()` for each, and persists `SymbolInfo`/`CallInfo`/`IncludeInfo` via `Repository`. After indexing, `ConfigTracker.scan_all()` does a second pass to populate config tables.
- **Config tracking**: `ConfigTracker` loads compiled regexes from `config_patterns` table, scans every source line, classifies each hit (`CONDITION | ASSIGNMENT | CALL_ARG | RETURN | OTHER`), and writes to `config_sources` + `config_usages`.
- **Graph queries**: `CallGraph.build()` loads all resolved call edges into a `networkx.DiGraph`. `PathTracer` wraps the graph with higher-level queries (BFS chains, all-simple-paths, recursive tree building).

---

## Database schema (v3)

| Table | Purpose |
|---|---|
| `schema_meta` | `key=version` version guard |
| `projects` | One row per indexed root directory |
| `files` | One row per source file; stores SHA-256 hash for incremental indexing |
| `symbols` | Functions, methods, classes, structs, variables, enums; unique by `usr` (clang USR) |
| `calls` | Directed call edges `caller_id → callee_id`; `callee_id` may be NULL if unresolved |
| `includes` | `#include` directives |
| `config_patterns` | Loaded from `config_patterns.yaml`; full-replaced on each `index` run |
| `config_sources` | Where a config key is first read/defined (file, line, enclosing function) |
| `config_usages` | All uses of a config key and whether they affect control flow |

SQLite is opened in **WAL mode** with **foreign keys ON**. The `Repository` class owns all SQL; never write raw SQL elsewhere.

---

## Entry points

| Command | Module | Purpose |
|---|---|---|
| `cpp-analyzer` | `cpp_analyzer.cli.commands:cli` | Full-featured CLI |
| `cpp-analyzer-mcp` | `cpp_analyzer.mcp_server:main` | Stdio MCP server |
| `python -m cpp_analyzer` | `cpp_analyzer.__main__` | Same as `cpp-analyzer` |

---

## CLI commands

```bash
# Index a C++ project (creates/updates cpp_analysis.db)
cpp-analyzer index ./my_project --db analysis.db [--name MyProject] [--force] [--clang-args "-I/usr/include/foo"]

# Database statistics
cpp-analyzer stats --db analysis.db

# Query symbols by name
cpp-analyzer query symbol "NetworkManager" [--kind FUNCTION] [--limit 30]

# List all config keys or show usages of one key
cpp-analyzer query config --list --db analysis.db
cpp-analyzer query config "max_threads" --db analysis.db

# Trace call chains activated by a config key
cpp-analyzer trace config "debug_mode" --depth 5 --chains 20

# Find all call paths between two functions
cpp-analyzer trace path "main" "processRequest" --max-paths 10

# Display a call tree
cpp-analyzer tree "processRequest" --direction down --depth 4
cpp-analyzer tree "processRequest" --direction up

# Show callers or callees of a function
cpp-analyzer who "loadConfig" --direction callers --depth 2

# Generate a Markdown report
cpp-analyzer report --output report.md
```

Default DB file is `cpp_analysis.db` in the current directory.

---

## MCP server tools

The MCP server exposes the same capabilities as tool calls:

| Tool | Description |
|---|---|
| `index_project(directory, db_path?, project_name?, force?)` | Parse and index a C++ directory |
| `get_stats(db_path?, project_id?)` | Project statistics |
| `list_config_keys(db_path?, project_id?)` | All detected config keys |
| `query_config(config_key, db_path?, project_id?)` | Usages of a specific config key |
| `trace_config(config_key, …, max_depth?, max_chains?)` | Call chains activated by a config key |
| `trace_path(source_function, target_function, …, max_paths?)` | Paths between two functions |
| `call_tree(function_name, direction?, …, max_depth?)` | Call tree rooted at a function |
| `search_symbols(query, kind?, …, limit?)` | Symbol search |

Run the MCP server: `cpp-analyzer-mcp` (stdio transport).

Claude Desktop config (`~/.claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "uv",
      "args": ["--directory", "/path/to/cpp-analyzer", "run", "cpp-analyzer-mcp"]
    }
  }
}
```

The default DB can be set via the `CPP_ANALYZER_DB` environment variable.

---

## Config patterns (`config_patterns.yaml`)

Each entry has:
```yaml
- name: "getenv"          # unique identifier
  type: ENV_VAR           # category: ENV_VAR | CONFIG_MAP | GFLAGS | CLI_ARG | JSON_CONFIG | YAML_CONFIG | PREPROCESSOR
  description: "…"
  regex: 'getenv\s*\(\s*"([^"]+)"'
  key_group: 1            # regex capture group that holds the config key name
```

Supported pattern types: `ENV_VAR`, `CONFIG_MAP`, `GFLAGS`, `CLI_ARG`, `JSON_CONFIG`, `YAML_CONFIG`, `PREPROCESSOR`.

To add a new pattern: add an entry to `config_patterns.yaml` and re-run `cpp-analyzer index` (patterns are synced on every index run — the full `config_patterns` table is replaced).

---

## Development setup

```bash
# Recommended: uv
uv pip install -e ".[dev]"

# Or: pip
pip install -e .
```

**Python ≥ 3.9** is required.

### Dependencies

| Package | Role |
|---|---|
| `libclang ≥ 16` | C++ AST parsing (optional — regex fallback activates if absent) |
| `click ≥ 8` | CLI framework |
| `rich ≥ 13` | Terminal output (tables, trees, progress) |
| `networkx ≥ 3` | In-memory call graph (DiGraph) |
| `PyYAML ≥ 6` | Parsing `config_patterns.yaml` |
| `tabulate ≥ 0.9` | Tabular output helper |
| `mcp ≥ 1.0` | MCP server (only in `pyproject.toml`; not in `requirements.txt`) |

libclang is optional at runtime — the `ClangParser` silently falls back to regex-based extraction when `import clang.cindex` fails. The fallback captures function/class definitions and includes but **not** call edges.

### Quick smoke-test

```bash
# Index the bundled sample
cpp-analyzer index ./examples --db test.db
cpp-analyzer stats --db test.db
cpp-analyzer query config --list --db test.db
cpp-analyzer trace config "DEBUG_MODE" --db test.db
```

---

## Code conventions

- **All SQL lives in `cpp_analyzer/db/repository.py`**. Do not issue raw SQL from analysis or CLI code.
- **Schema changes** require bumping `SCHEMA_VERSION` in `db/schema.py` and adding migration logic if needed. Current version: **3**.
- **Parser results are pure data** (`ParseResult`, `SymbolInfo`, `CallInfo`, `IncludeInfo` are `@dataclass`). No DB interaction inside `ast_parser.py`.
- **`Repository.transaction()`** is a context manager that commits on success and rolls back on exception. Use it for all writes.
- **Incremental indexing**: files are skipped when their SHA-256 hash matches the stored value. Pass `--force` / `force=True` to override.
- **`ClangParser` is stateful** (holds a `clang.Index`). One instance is created per `Indexer` run. Do not share across threads.
- **`CallGraph.build()`** must be called before any graph query. Subsequent calls to `callers_of`, `callees_of`, etc. are read-only on the `networkx.DiGraph`.
- **Skipped directories during indexing**: `build/`, `cmake-build-debug/`, `cmake-build-release/`, `node_modules/`, `_deps/`, `third_party/`, `vendor/`, and any hidden directory (`.`-prefixed).
- **File extensions indexed**: `.cpp .cc .cxx .c .C .h .hpp .hxx .hh`.
- **Symbol kinds stored**: `FUNCTION`, `METHOD`, `CONSTRUCTOR`, `DESTRUCTOR`, `CLASS`, `STRUCT`, `CLASS_TEMPLATE`, `FUNCTION_TEMPLATE`, `VARIABLE`, `FIELD`, `ENUM`, `ENUM_CONSTANT`, `NAMESPACE`, `TYPEDEF`, `TYPE_ALIAS`.
- **Multi-project support**: the DB supports multiple projects. Commands default to the only project if exactly one exists; otherwise `--project-id` is required.
- **Generated files** (`*.db`, `*.db-wal`, `*.db-shm`) are `.gitignore`d and should never be committed.
- Python style follows standard PEP 8; use `from __future__ import annotations` for forward-ref compatibility (already used throughout).

---

## When adding a new CLI command

1. Add a `@cli.command()` (or `@<group>.command()`) in `cpp_analyzer/cli/commands.py`.
2. If it needs graph or trace logic, add a method to `CallGraph` or `PathTracer` and expose it through `Repository` if DB access is needed.
3. Mirror the command as a `@mcp.tool()` in `cpp_analyzer/mcp_server.py` with a clear docstring (the docstring becomes the tool description for MCP clients).

## When adding a new config pattern type

1. Add entries to `config_patterns.yaml`.
2. Verify the regex captures the key in the correct group (`key_group`).
3. Re-index with `--force` to repopulate the `config_patterns` and `config_sources` tables.
4. No code changes are needed — `ConfigTracker` loads patterns dynamically from the DB.
