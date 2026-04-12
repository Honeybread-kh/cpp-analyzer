# Analyst Report: 테인트 분석 기반 다단계 데이터 플로우 추적

## 1. 영향받는 파일과 변경 범위

### 수정 대상 (6개)
- **ts_parser.py**: `extract_all_assignments()`, `extract_call_arguments()` 추가
- **models.py**: `TaintNode`, `DataFlowPath` dataclass 추가
- **schema.py**: `call_args`, `dataflow_paths` 테이블, SCHEMA_VERSION 5→6
- **repository.py**: call_args/dataflow_paths CRUD + `_migrate_to_v6()`
- **commands.py**: `@trace.command("dataflow")` 추가
- **mcp_server.py**: `@mcp.tool() trace_dataflow` 추가

### 신규 파일 (1개)
- **taint_tracker.py**: `AliasMap`, `TaintTracker` 클래스

## 2. 기존 코드 패턴

### ts_parser.py
- 반환: 항상 `list[dict]` (dataclass 아님)
- 순회: `walk_type(root, "node_type")` → `child_by_field_name()` → `node_text()`
- 헬퍼: `_find_enclosing_function()`, `_get_function_name()`

### models.py
- `@dataclass`, 필수 필드 먼저, 기본값 뒤에
- `str | None` 타입 힌트, `CSV_HEADERS` + `csv_row()` 메서드

### config_dependency.py (TaintTracker 참고)
- `__init__(repo, project_id, target_structs)` → `analyze() -> AnalysisResult`
- 파일별 루프: `repo.list_files()` → `ts_parser.parse_file()` → `ts_parser.extract_XXX()`

### repository.py
- insert: `_conn` 키워드 인자 + `self.transaction()` 컨텍스트
- query: `self._conn.execute().fetchone/fetchall()`
- 마이그레이션: `_apply_schema()` 내 버전 체크 분기

### commands.py
- `@trace.command("subcommand")` + `_get_repo(db)` + `_resolve_project()` 보일러플레이트
- `rich.Table`/`rich.Tree` 출력

### mcp_server.py
- `@mcp.tool()` + `_default_db()` + `_repo()` + `_resolve_project_id()` 보일러플레이트
- 반환 항상 `str`

## 3. 구현 순서 (확정)
A (ts_parser) → B (schema + repository) → C+D (taint_tracker + 패턴) → E (CLI + MCP)

## 4. 주의 사항
- tree-sitter-c 사용 중 → C++ auto/namespace 파싱 제한 가능
- `init_declarator` (선언+초기화)도 대입으로 추적 필요
- 복합 대입 (`+=`, `|=`) 처리
- 순환 참조 방지 (visited set)
- 다중 경로 폭발 방지 (max_depth + max_paths)
- call_args FK에 ON DELETE CASCADE 필수
