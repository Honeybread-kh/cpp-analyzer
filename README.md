# cpp-analyzer

C/C++ static analyzer. Indexes symbols, call graphs, config keys, and dataflow (taint) traces into a single SQLite DB, queryable via **CLI** and **MCP server**.

Key features:

- **libclang**-based symbol/call graph + **tree-sitter**-based assignment/dataflow extraction
- **Config tracking**: collects config keys via regex patterns (`getenv`, `FLAGS_*`, `struct_ptr->field = val`, etc.)
- **Taint dataflow**: inter-procedural tracing from `cfg->field` → intermediate transforms → `REG_WRITE(...)` / `regmap_write(...)` / MMIO
- **Incremental re-indexing**: file SHA256 hash-based skip. Built-in `parse_cache` + `trace_result_cache` make 2nd+ runs 10–30× faster.
- **CLI ↔ MCP mirroring**: every CLI command has a corresponding MCP tool.

## Requirements

- Python ≥ 3.9
- libclang (LLVM/Clang)
  - macOS: `brew install llvm`
  - Ubuntu: `sudo apt install libclang-dev`

## Installation

```bash
cd cpp-analyzer
pip install -e .
```

To use as an MCP server:

```bash
pip install mcp
```

## Quick Start

All subcommands must share the **same `--db` path**. Do not change `--db` during a project analysis session (a different DB will not see prior indexing results).

```bash
# 1) Index (first run; subsequent runs are automatically incremental)
cpp-analyzer index ./src --db ./proj.db --name myproj

# 2) Symbol search / call graph / dataflow
cpp-analyzer query symbol "parse_header" --db ./proj.db
cpp-analyzer tree "init_device"          --db ./proj.db --direction down --depth 4
cpp-analyzer trace dataflow              --db ./proj.db --save
cpp-analyzer trace query                 --db ./proj.db --source "cfg->" --sink "regs\["
```

## CLI Reference

All examples below require the `--db <path>` option (can be omitted to use the default, but explicit specification is recommended).

### `index` — Parse & write to DB

```bash
cpp-analyzer index <dir> [<dir2> ...] \
  --db ./proj.db \
  [--name <project_name>] \
  [--patterns ./config_patterns.yaml] \
  [--force] \
  [--no-cache] \
  [--clang-args "-I./include,-DFOO"]
```

- `--name` defaults to the first directory name if omitted
- `--patterns` config key extraction patterns (see "Config pattern YAML" below)
- `--force` force re-parse even for unchanged files
- `--no-cache` bypass `parse_cache` / `config_scan_state` (for debugging)

Files whose hash has not changed are automatically skipped, making re-runs fast.

### `query` — Index lookups

```bash
cpp-analyzer query symbol <name> --db ./proj.db [--kind FUNCTION|STRUCT|...] [--limit N]

cpp-analyzer query config --list                --db ./proj.db     # all config keys
cpp-analyzer query config <key>                 --db ./proj.db     # usages of a specific key
```

### `tree` / `who` — Call graph

```bash
cpp-analyzer tree <function> --db ./proj.db --direction down --depth 5   # callees
cpp-analyzer tree <function> --db ./proj.db --direction up   --depth 4   # callers

cpp-analyzer who  <function> --db ./proj.db --direction callers
cpp-analyzer who  <function> --db ./proj.db --direction callees --depth 2
```

### `trace config` — Config key impact tracing

```bash
cpp-analyzer trace config <key> --db ./proj.db --depth 5 --chains 20
```

Starting from conditionals that reference `key`, follows call chains to show how far the impact propagates.

### `trace path` — Call path between two functions

```bash
cpp-analyzer trace path <from> <to> --db ./proj.db [--max-paths 10]
```

### `trace dataflow` — Taint / dataflow analysis

```bash
# Default patterns (cfg->field → REG_WRITE/regmap_write/MMIO)
cpp-analyzer trace dataflow --db ./proj.db --save

# Using a YAML pattern file
cpp-analyzer trace dataflow --db ./proj.db --patterns ./patterns/mydriver.yaml --save

# Inline regex (one-off)
cpp-analyzer trace dataflow --db ./proj.db \
  --source 'cfg->(\w+)' --sink 'writel\s*\(' --save

# Reverse trace (backward from sink)
cpp-analyzer trace dataflow --db ./proj.db --reverse 'REG_WRITE\s*\('

# JSON output
cpp-analyzer trace dataflow --db ./proj.db --format json
```

Options:
- `--source <regex>` / `--sink <regex>` can be specified multiple times. When specified, fully replaces that axis.
- `--patterns <yaml>` loads patterns from a file (see "Dataflow pattern YAML" below).
- `--depth <N>` max inter-procedural trace depth (default 5).
- `--max-paths <N>` max number of returned paths (default 100).
- `--save` persists results to the `dataflow_paths` table for later re-query via `trace query`.
- `--no-cache` bypasses `parse_cache` / `trace_result_cache`.

### `trace query` — Query saved dataflow paths

Re-queries results persisted by `trace dataflow --save` **without re-running analysis**.

```bash
cpp-analyzer trace query --db ./proj.db \
  --source "cfg->freq" --sink "regs\[" --limit 50 --format tree
```

### `config-spec` — Config field spec extraction

Outputs per-struct-field enum/range/default, register sink, and transform as CSV/JSON/YAML.

```bash
cpp-analyzer config-spec --db ./proj.db --format csv  --output specs.csv
cpp-analyzer config-spec --db ./proj.db --format yaml --language   # constraint language
```

### `stats` / `report`

```bash
cpp-analyzer stats  --db ./proj.db
cpp-analyzer report --db ./proj.db --output report.md
```

### `deps` — Include dependencies

```bash
cpp-analyzer deps <file> --db ./proj.db [--direction both|up|down] [--circular]
```

## Config pattern YAML

File passed to `index --patterns` — **a regex catalog for extracting config key names from source text**.

```yaml
patterns:
  - name: getenv
    type: ENV_VAR
    description: POSIX getenv() call
    regex: 'getenv\s*\(\s*"([^"]+)"'
    key_group: 1

  - name: struct_ptr_assign
    type: STRUCT_FIELD
    description: "ptr->field = value"
    regex: '(\w+)->(\w+)\s*=\s*(.+?)\s*;'
    key_group: 2   # 2nd capture group = field name stored as config_key
```

- `key_group`: which regex capture group is the config key. Defaults to 1 if omitted; 0 means the entire match string.
- `type`: arbitrary classification tag — `ENV_VAR` / `CLI_ARG` / `GFLAGS` / `STRUCT_FIELD` / `PREPROCESSOR` / `CONFIG_MAP` etc.
- A default `config_patterns.yaml` is included in the repository; copy and customize it per project.

## Dataflow pattern YAML

File passed to `trace dataflow --patterns` / `config-spec --patterns` / `trace_dataflow(patterns_file=...)` — **defines taint sources and sinks**.

```yaml
sources:
  - name: config_field
    regex: '(?:cfg|conf|config|param)\w*->(\w+)'

  - name: ioctl_user_arg
    regex: 'user_req->(\w+)'

sinks:
  - name: REG_WRITE
    regex: 'REG_WRITE\s*\(\s*([^,]+)\s*,'

  # MMIO: writel(val, addr) — value is the 0th argument
  - name: mmio_writel
    regex: '\b(?:writel|writel_relaxed|__raw_writel|iowrite8|iowrite16|iowrite32)\s*\('
    value_arg: 0

  # regmap family: regmap_write(map, reg, val) — value is the last argument (default behavior)
  - name: regmap_write
    regex: '\bregmap_(?:write|update_bits|set_bits|clear_bits|write_bits)\s*\('

  - name: reg_arrow_assign
    regex: '(?:reg|regs|hw_reg|io_regs)\w*->(\w+)\s*='
```

Rules:

- The **first capture group** of `sources[].regex` is the source variable name. If none, the entire match is used.
- `sinks[].regex` matches against assignment LHS or call expressions to identify sinks.
- `value_arg: N` specifies the Nth argument as the taint value in call-form sinks. Defaults to the **last argument** if omitted.
- Single-quote YAML strings are recommended to preserve `\w`, `\s` literals.
- Built-in defaults are in `cpp_analyzer/analysis/taint_tracker.py` (`DEFAULT_SOURCE_PATTERNS` / `DEFAULT_SINK_PATTERNS`).

## MCP Server

### Configuration

`.mcp.json` example:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "cpp-analyzer-mcp"
    }
  }
}
```

After `pip install -e .`, the `cpp-analyzer-mcp` entry point is available directly. To start as a Python module:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "cpp_analyzer.mcp_server"],
      "cwd": "/abs/path/to/cpp-analyzer"
    }
  }
}
```

The DB path is passed via the `db_path` parameter in tool calls, or can be fixed via environment variable.

### MCP Tools

| Tool | Description |
|------|-------------|
| `index_project` | Index a source directory (required before other tools) |
| `search_symbols` | Search symbols by name/kind |
| `call_tree` | Function call tree (down/up) |
| `trace_path` | Call path between two functions |
| `trace_config` | Call chains activated by a config key |
| `query_config` | Config key usages + control flow impact |
| `list_config_keys` | All collected config keys |
| `analyze_configs` | Struct-field based config dependency analysis |
| `export_configs_csv` / `export_configs_kconfig` | Config analysis export |
| `trace_dataflow` | Taint dataflow (forward). Persist with `save=True`. |
| `reverse_trace_dataflow` | Backward taint from sink |
| `query_dataflow_paths` | Re-query saved dataflow_paths (no re-analysis) |
| `export_config_spec` | Struct field spec (enum/range/sink) as CSV/JSON/YAML |
| `file_dependencies` / `circular_dependencies` / `dependency_stats` | Include dependencies |
| `get_stats` | Project indexing statistics |

### Typical MCP workflow

```
index_project(directory="/abs/src", db_path="/abs/proj.db", name="myproj")
trace_dataflow(db_path="/abs/proj.db", patterns_file="/abs/patterns/myproj.yaml", save=True)
query_dataflow_paths(db_path="/abs/proj.db", source_var="cfg->", sink_var="regs[", limit=50)
```

## Caching Model

Three hash-keyed caches eliminate repeated analysis cost. All auto-invalidate when file hashes change.

| Cache | Scope | Key | Invalidation |
|-------|-------|-----|--------------|
| `parse_cache` | Per-file tree-sitter extraction results | `(file_id, file_hash)` | File hash change or FK cascade |
| `config_scan_state` | Per-file config regex scan state | `(file_id, scan_hash)` | File hash change |
| `trace_result_cache` | trace() query results | `(project_id, pattern_hash, project_fingerprint)` | Any file hash change causes fingerprint mismatch |

Bypass all caches with `--no-cache` / `use_cache=False`.

## Limitations

- **Pure C projects**: uses libclang's C++ parser, so some parse errors may occur (limited impact on analysis results).
- **Function pointers**: array / struct member / local alias-based dispatch is largely tracked, but complete indirect call resolution is not possible.
- **Macro expansion**: complex macro chains are only partially traced.

## Project Layout

```
cpp-analyzer/
├── cpp_analyzer/
│   ├── __main__.py
│   ├── mcp_server.py          # FastMCP server
│   ├── cli/commands.py        # click CLI
│   ├── core/
│   │   ├── indexer.py         # Indexing pipeline (incremental)
│   │   └── ast_parser.py      # libclang wrapper
│   ├── analysis/
│   │   ├── call_graph.py
│   │   ├── path_tracer.py
│   │   ├── config_tracker.py  # Config key extraction
│   │   ├── taint_tracker.py   # Dataflow/taint engine + default patterns
│   │   ├── ts_parser.py       # tree-sitter based assignment/range/enum extraction
│   │   └── models.py          # ConfigParam / ConfigFieldSpec / DataFlowPath
│   └── db/
│       ├── schema.py          # SCHEMA_VERSION, CREATE TABLE
│       └── repository.py      # All DB access functions
├── tests/
│   ├── test_dataflow.py       # Fixture-based benchmark tests
│   ├── test_parse_cache.py    # Cache layer unit tests
│   └── fixtures/dataflow/
├── scripts/
│   ├── bench_parse_cache.py
│   └── profile_trace.py
├── config_patterns.yaml       # Default config key patterns
└── pyproject.toml
```
