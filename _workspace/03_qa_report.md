# QA Report: CLI/MCP + Export + Reverse Trace + Config Language

**날짜:** 2026-04-13

## 실행 테스트

| 테스트 | 결과 |
|--------|------|
| tests/test_dataflow.py (37 tests) | PASS |
| tests/test_dependency_graph.py (20 tests) | PASS |
| **Total: 57/57** | **ALL PASS** |

Benchmark score: 45/45 (100%)

## 경계면 검증 5종

### V1: CLI↔MCP 미러링 — PASS
| CLI | MCP | 상태 |
|-----|-----|------|
| `trace dataflow` | `trace_dataflow()` | PASS |
| `trace dataflow --reverse` | `reverse_trace_dataflow()` | PASS |
| `config-spec` | `export_config_spec()` | PASS |

### V2: DB↔Analysis 정합성 — PASS
- ConfigFieldSpec 확장 필드 (gated_by, gates, co_depends)는 메모리 내 분석용, DB 테이블 변경 없음

### V3: Analysis↔Repository — PASS
- taint_tracker의 새 메서드들은 기존 repository 인터페이스만 사용

### V4: 테스트 커버리지 — PASS
- TestReverseTrace: 2 tests (source 발견, sink별 그룹핑)
- TestConfigExport: 3 tests (CSV/JSON/YAML 형식)
- TestConfigLanguage: 4 tests (구조, 필드, gating, co-dependency)

### V5: Import/의존성 정합성 — PASS
- export 함수들은 모듈 레벨 함수로 추가 (import 정상)

## Regression 확인
- 기존 48 tests 전부 PASS
- 신규 9 tests 전부 PASS
- **Regression 없음**

## 결론
**ALL PASS** — 커밋 가능
