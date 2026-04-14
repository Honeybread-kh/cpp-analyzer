"""
Database schema: all CREATE TABLE / CREATE INDEX statements.
"""

SCHEMA_VERSION = 7

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── meta ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ── project ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    root_path  TEXT    NOT NULL,           -- JSON array of root paths
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_indexed DATETIME
);

-- ── source files ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path          TEXT    NOT NULL,          -- absolute path
    relative_path TEXT    NOT NULL,
    file_hash     TEXT,                      -- SHA256 for change detection
    last_modified REAL,                      -- os.path.getmtime()
    last_indexed  DATETIME,
    line_count    INTEGER,
    UNIQUE(project_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);

-- ── symbols (functions, methods, classes, variables, enums …) ────────────────
CREATE TABLE IF NOT EXISTS symbols (
    id             INTEGER PRIMARY KEY,
    file_id        INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name           TEXT    NOT NULL,
    qualified_name TEXT,                     -- namespace::Class::method
    kind           TEXT    NOT NULL,         -- FUNCTION | METHOD | CLASS | STRUCT |
                                             -- VARIABLE | ENUM | CONSTRUCTOR | …
    signature      TEXT,
    line_start     INTEGER,
    line_end       INTEGER,
    col_start      INTEGER,
    is_definition  INTEGER DEFAULT 0,
    is_declaration INTEGER DEFAULT 0,
    parent_id      INTEGER REFERENCES symbols(id),
    namespace_path TEXT,                     -- e.g. "myapp::net"
    visibility     TEXT,                     -- public | private | protected
    return_type    TEXT,
    usr            TEXT UNIQUE,             -- clang Unified Symbol Resolution
    template_params TEXT                    -- e.g. "typename T, int N"
);
CREATE INDEX IF NOT EXISTS idx_symbols_file     ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name     ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qname    ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind     ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_usr      ON symbols(usr);

-- ── call edges ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calls (
    id            INTEGER PRIMARY KEY,
    caller_id     INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    callee_name   TEXT    NOT NULL,
    callee_id     INTEGER REFERENCES symbols(id),   -- NULL if unresolved
    call_file_id  INTEGER NOT NULL REFERENCES files(id),
    call_line     INTEGER,
    call_col      INTEGER,
    code_snippet  TEXT,
    call_type     TEXT DEFAULT 'direct'     -- direct | indirect
);
CREATE INDEX IF NOT EXISTS idx_calls_caller  ON calls(caller_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee  ON calls(callee_id);
CREATE INDEX IF NOT EXISTS idx_calls_name    ON calls(callee_name);

-- ── #include edges ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS includes (
    id                 INTEGER PRIMARY KEY,
    file_id            INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    included_file_id   INTEGER REFERENCES files(id),
    included_path      TEXT    NOT NULL,
    line               INTEGER,
    is_system          INTEGER DEFAULT 0
);

-- ── config pattern registry ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config_patterns (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    pattern_type TEXT    NOT NULL,
    description  TEXT,
    regex        TEXT    NOT NULL,
    key_group    INTEGER DEFAULT 1,
    is_active    INTEGER DEFAULT 1
);

-- ── config sources: where a config key is first read / defined ────────────────
CREATE TABLE IF NOT EXISTS config_sources (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES files(id),
    symbol_id   INTEGER REFERENCES symbols(id),  -- enclosing function
    pattern_id  INTEGER REFERENCES config_patterns(id),
    config_key  TEXT    NOT NULL,
    line        INTEGER,
    col         INTEGER,
    code_snippet TEXT,
    UNIQUE(file_id, line, col, config_key)
);
CREATE INDEX IF NOT EXISTS idx_csrc_key     ON config_sources(config_key);
CREATE INDEX IF NOT EXISTS idx_csrc_file    ON config_sources(file_id);
CREATE INDEX IF NOT EXISTS idx_csrc_symbol  ON config_sources(symbol_id);

-- ── config usages: every place a config key influences logic ──────────────────
CREATE TABLE IF NOT EXISTS config_usages (
    id                   INTEGER PRIMARY KEY,
    source_id            INTEGER REFERENCES config_sources(id),
    file_id              INTEGER NOT NULL REFERENCES files(id),
    symbol_id            INTEGER REFERENCES symbols(id),
    config_key           TEXT    NOT NULL,
    usage_type           TEXT,     -- CONDITION | ASSIGNMENT | CALL_ARG | RETURN | OTHER
    affects_control_flow INTEGER DEFAULT 0,
    line                 INTEGER,
    col                  INTEGER,
    code_snippet         TEXT
);
CREATE INDEX IF NOT EXISTS idx_cusage_key    ON config_usages(config_key);
CREATE INDEX IF NOT EXISTS idx_cusage_symbol ON config_usages(symbol_id);

-- ── class inheritance ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS class_inheritance (
    id                INTEGER PRIMARY KEY,
    class_symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    base_class_name   TEXT NOT NULL,
    base_class_usr    TEXT,
    base_class_id     INTEGER REFERENCES symbols(id),
    access            TEXT,
    is_virtual        INTEGER DEFAULT 0,
    UNIQUE(class_symbol_id, base_class_name)
);
CREATE INDEX IF NOT EXISTS idx_inheritance_class ON class_inheritance(class_symbol_id);
CREATE INDEX IF NOT EXISTS idx_inheritance_base  ON class_inheritance(base_class_id);

-- ── call arguments (for inter-procedural dataflow) ──────────────────────────
CREATE TABLE IF NOT EXISTS call_args (
    id             INTEGER PRIMARY KEY,
    call_id        INTEGER NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    arg_index      INTEGER NOT NULL,
    arg_expression TEXT,                        -- caller-side actual argument text
    param_name     TEXT                         -- callee-side parameter name
);
CREATE INDEX IF NOT EXISTS idx_callargs_call ON call_args(call_id);

-- ── dataflow paths (taint analysis results) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS dataflow_paths (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_var  TEXT    NOT NULL,               -- config field name
    sink_var    TEXT    NOT NULL,               -- register / final target
    path_json   TEXT    NOT NULL,               -- JSON: [{var, transform, file, line, function}, ...]
    depth       INTEGER,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dfpaths_project ON dataflow_paths(project_id);
CREATE INDEX IF NOT EXISTS idx_dfpaths_source  ON dataflow_paths(source_var);

-- ── parse entity cache (hash-keyed by files.file_hash) ──────────────────────
CREATE TABLE IF NOT EXISTS parse_cache (
    file_id    INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    file_hash  TEXT    NOT NULL,
    payload    TEXT    NOT NULL,     -- JSON of extracted entities
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_parse_cache_hash ON parse_cache(file_hash);

-- ── config scan state (hash-gate for ConfigTracker.scan_all) ─────────────────
CREATE TABLE IF NOT EXISTS config_scan_state (
    file_id    INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    scan_hash  TEXT    NOT NULL,
    scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""
