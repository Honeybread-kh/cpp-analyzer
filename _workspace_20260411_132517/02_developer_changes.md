# Developer Changes: 테인트 분석 기반 다단계 데이터 플로우 추적

## 변경 파일

### 수정 (6개)
1. **cpp_analyzer/analysis/ts_parser.py** — 3개 함수 추가:
   - `extract_all_assignments()`: 함수 내 모든 대입문(assignment + init_declarator) 추출
   - `extract_call_arguments()`: 호출식의 실인자 추출
   - `extract_function_params()`: 함수 파라미터 목록 추출
   - `_extract_variables()`: 표현식 내 변수/필드 참조 추출 (헬퍼)

2. **cpp_analyzer/analysis/models.py** — 2개 dataclass 추가:
   - `TaintNode`: 데이터 플로우 체인의 각 노드
   - `DataFlowPath`: source→sink 전체 경로 (format_chain() 시각화)

3. **cpp_analyzer/db/schema.py** — SCHEMA_VERSION 5→6, 2개 테이블 추가:
   - `call_args`: 호출 인자↔파라미터 매핑
   - `dataflow_paths`: 분석 결과 저장

4. **cpp_analyzer/db/repository.py** — 마이그레이션 + CRUD:
   - `_migrate_to_v6()`, `insert_call_arg()`, `get_call_args()`
   - `insert_dataflow_path()`, `get_dataflow_paths()`, `delete_dataflow_paths()`
   - `stats()`에 dataflow_paths 카운트 추가

5. **cpp_analyzer/cli/commands.py** — `trace dataflow` 커맨드 추가:
   - `--source`, `--sink`, `--depth`, `--max-paths`, `--save`, `--format` 옵션

6. **cpp_analyzer/mcp_server.py** — `trace_dataflow` MCP 도구 추가:
   - CLI와 동일 인자, str 반환

### 신규 (1개)
7. **cpp_analyzer/analysis/taint_tracker.py** — 핵심 엔진:
   - `AliasMap`: 포인터 앨리어스 추적 (체인 해석)
   - `TaintTracker`: 다단계 역추적 엔진
   - 기본 Source/Sink 패턴 상수

## 검증 결과
- 모든 모듈 import 성공
- ts_parser: C 코드 파싱, 대입문/호출인자/파라미터 추출 정상
- AliasMap: 앨리어스 체인 해석 정상
- DB: schema v6 마이그레이션, 테이블 생성 정상
- CLI: `trace dataflow --help` 정상
