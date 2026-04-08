# cpp-analyzer

A static analysis tool for C/C++ source code that tracks symbols, call relationships, and configuration (macro/define) usage across the codebase.

Available as both a CLI tool and an MCP server.

## Requirements

- Python >= 3.9
- libclang (requires LLVM/Clang installed on the system)
  - macOS: `brew install llvm`
  - Ubuntu: `sudo apt install libclang-dev`

## Installation

```bash
cd cpp-analyzer
pip install -e .
```

To use as an MCP server, install the additional dependency:

```bash
pip install mcp
```

## Usage

### Step 1: Index the Project

All analysis features require indexing first.

```bash
# Basic indexing
cpp-analyzer index /path/to/source --db analysis.db

# Force re-index all files
cpp-analyzer index /path/to/source --db analysis.db --force
```

Indexing results are stored in a SQLite database file (`cpp_analysis.db` by default).

### Step 2: Analyze

#### Symbol Search

Search for functions, structs, variables, macros, etc. by name.

```bash
cpp-analyzer query symbol "jpeg_compress_struct"
cpp-analyzer query symbol "NetworkManager" --kind FUNCTION
```

#### Call Tree

Display the call tree of a function — what it calls (down) or who calls it (up).

```bash
# What does this function call?
cpp-analyzer tree "prepare_for_pass" --direction down --depth 5

# Who calls this function?
cpp-analyzer tree "emit_sos" --direction up --depth 4
```

#### Call Path Tracing

Find call paths between two functions.

```bash
cpp-analyzer trace path "main" "processRequest"
```

#### Configuration Analysis

List and inspect config keys used in the codebase.

```bash
# List all config keys
cpp-analyzer query config --list

# Show usages of a specific key
cpp-analyzer query config "Ss"

# Trace call chains affected by a config key
cpp-analyzer trace config "debug_mode" --depth 5 --chains 20
```

#### Callers / Callees

```bash
cpp-analyzer who "emit_sos" --direction callers
cpp-analyzer who "emit_sos" --direction callees --depth 2
```

#### Statistics and Reports

```bash
cpp-analyzer stats --db analysis.db
cpp-analyzer report --output report.md
```

## MCP Server

Enables AI assistants (e.g., Claude Code) to perform code analysis directly via the MCP protocol.

### Configuration

Create a `.mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "python",
      "args": ["-m", "cpp_analyzer.mcp_server"],
      "cwd": "/path/to/cpp-analyzer"
    }
  }
}
```

Or, after `pip install -e .`, use the entry point directly:

```json
{
  "mcpServers": {
    "cpp-analyzer": {
      "command": "cpp-analyzer-mcp"
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `index_project` | Parse and index a source directory into the DB (required before any other tool) |
| `search_symbols` | Search symbols by name (functions, structs, variables, etc.) |
| `call_tree` | Display call tree rooted at a function (up/down) |
| `trace_path` | Find call paths between two functions |
| `trace_config` | Trace call chains transitively activated by a config key |
| `query_config` | Show where a config key is used and how it affects control flow |
| `list_config_keys` | List all detected config keys |
| `get_stats` | Show project indexing statistics |
| `analyze_configs` | Analyze struct-field-based config dependencies (CSV/KConfig output) |
| `export_configs_csv` | Return config analysis results as CSV text |
| `export_configs_kconfig` | Return config analysis results in KConfig format |

### MCP Workflow

```
1. index_project(directory="/path/to/source")          # Index the codebase
2. search_symbols(query="function_name")               # Search for symbols
3. call_tree(function_name="func", direction="up")     # Explore call relationships
4. trace_config(config_key="MACRO_NAME")               # Trace config impact
```

## Limitations

- **C code parsing**: Uses libclang's C++ parser, so pure C projects may produce some parse errors. This has minimal impact on analysis results.
- **Function pointers**: Indirect calls through function pointers (e.g., `(*cinfo->entropy->start_pass)(cinfo, ...)`) cannot be tracked by static analysis. Some paths may be missing in `call_tree` or `trace_path` results.
- **Macro expansion**: Complex macro chains may not be fully traced.
- **Incremental indexing**: Only changed files are re-indexed. Use `--force` for a full re-index when needed.

## Project Structure

```
cpp-analyzer/
├── cpp_analyzer/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── mcp_server.py        # MCP server
│   ├── cli/
│   │   └── commands.py      # CLI command definitions
│   ├── core/
│   │   └── ast_parser.py    # libclang-based AST parser
│   ├── analysis/
│   │   ├── call_graph.py    # Call graph construction
│   │   ├── config_tracker.py # Config key tracking
│   │   └── path_tracer.py   # Path tracing (BFS/DFS)
│   └── db/
│       └── schema.py        # SQLite schema
├── examples/
│   └── sample.cpp
├── requirements.txt
└── setup.py
```
