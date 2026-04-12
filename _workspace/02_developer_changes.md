# Developer Changes Report

## 수정된 파일 목록

### 1. `cpp_analyzer/analysis/models.py`
- **ConfigFieldSpec** 에 3개 필드 추가: `gated_by`, `gates`, `co_depends`
- **CSV_HEADERS** 클래스 변수 추가 (15개 컬럼)
- **csv_row()** 메서드 추가 — 리스트 필드는 `"|".join(...)` 직렬화

### 2. `cpp_analyzer/analysis/ts_parser.py`
- **extract_gating_conditions(root)** 함수 추가
  - if문 condition에서 field_expression 추출
  - consequence 블록의 assignment에서 gated 변수 추출
  - subscript_expression (regs->regs[X] = ...) 패턴도 처리
  - `{gating_field, gated_vars, line, function}` 형태 반환

### 3. `cpp_analyzer/analysis/taint_tracker.py`
- **TaintTracker.reverse_trace(sink_pattern, max_depth)** 메서드 추가
  - sink 패턴으로 필터링 후 역추적, sink별 그룹핑 결과 반환
- **TaintTracker.detect_gating(specs, paths)** 메서드 추가
  - ts_parser.extract_gating_conditions() 기반 gated_by/gates 채움
- **TaintTracker.detect_co_dependencies(specs, paths)** 메서드 추가
  - 같은 sink에 기여하는 source 필드들의 co_depends 채움
- 모듈 레벨 함수 4개 추가:
  - **export_specs_csv(specs)** -> CSV 문자열
  - **export_specs_json(specs)** -> JSON 문자열
  - **export_specs_yaml(specs)** -> YAML 문자열
  - **export_config_language(specs, paths)** -> config constraint YAML

### 4. `cpp_analyzer/cli/commands.py`
- **trace dataflow --reverse** 플래그 추가 (sink 패턴 지정 시 역방향 추적)
- **--source** / **--sink** 옵션을 `multiple=True`로 변경 (복수 패턴 지원)
- **config-spec** 커맨드 추가
  - `--format csv|json|yaml`, `--output`, `--language` 옵션
  - `--source`, `--sink`, `--patterns`, `--depth` 공통 옵션

### 5. `cpp_analyzer/mcp_server.py`
- **reverse_trace_dataflow(sink_pattern, ...)** MCP 도구 추가
- **export_config_spec(format, ...)** MCP 도구 추가
  - `include_language=True`로 config constraint spec 내보내기 지원

### 6. `tests/test_dataflow.py`
- **TestReverseTrace** 클래스 추가 (2 tests)
  - reverse_trace가 source를 찾는지, sink별 그룹핑이 올바른지 검증
- **TestConfigExport** 클래스 추가 (3 tests)
  - CSV/JSON/YAML 내보내기 형식 및 필드 검증
- **TestConfigLanguage** 클래스 추가 (4 tests)
  - config language YAML 구조, gating 감지, co-dependency 감지 검증

## 테스트 결과
- 전체 57 tests PASSED (기존 48 + 신규 9)
- Regression 없음
