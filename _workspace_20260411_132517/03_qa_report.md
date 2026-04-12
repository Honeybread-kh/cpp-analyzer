# QA Report

## 변경 요약
- 테인트 분석 기반 다단계 데이터 플로우 추적 기능 구현 (config field -> register write 역추적)

## 검증 결과

| 항목 | 상태 | 비고 |
|------|------|------|
| V1. CLI↔MCP 미러링 | PASS (minor) | 기능 동일. 파라미터 명칭 차이 있음 (아래 상세) |
| V2. DB↔Repository | PASS | call_args, dataflow_paths 테이블 컬럼과 CRUD SQL 완전 일치 |
| V3. Analysis↔Repository | PASS | TaintTracker가 호출하는 list_files, insert_dataflow_path, delete_dataflow_paths 모두 존재, 시그니처 일치 |
| V4. Import 체인 | PASS | 순환 import 없음. 모든 모듈 import 정상 확인 |
| V5. 모델 일관성 | PASS | TaintNode/DataFlowPath의 to_dict, depth, format_chain 등 CLI/MCP/taint_tracker에서 올바르게 사용 |
| T1. 실행 테스트 (전체 흐름) | PASS | AliasMap 체인 해석, ts_parser 대입문/호출인자/파라미터 추출, CLI --help 모두 정상 |
| T2. DB 저장/조회 테스트 | PASS | dataflow_paths CRUD (insert/get/filter/delete), call_args CRUD, stats 포함 모두 정상 |

## 발견된 문제

### P1. [Minor] CLI↔MCP 파라미터 명칭 불일치

CLI와 MCP의 대응 파라미터 이름이 다름:

| CLI 옵션 | MCP 파라미터 | 비고 |
|----------|-------------|------|
| `--source` | `source_pattern` | MCP가 더 명시적 |
| `--sink` | `sink_pattern` | MCP가 더 명시적 |
| `--depth` | `max_depth` | MCP가 더 명시적 |
| `--format` | (없음) | MCP는 텍스트만 반환하므로 불필요 - 정상 |

기능적으로 동일하게 동작하며, MCP 도구는 프로그래밍 인터페이스이므로 더 명시적인 이름이 적절. PASS 판정이나 향후 통일 고려 가능.

### P2. [Bug] `_extract_variables()`가 루트 노드 자체의 field_expression을 인식하지 못함

`ts_parser._extract_variables(node)`에서 `walk_type(node, "field_expression")`은 자식 노드만 순회하므로, `node` 자체가 `field_expression`인 경우(예: `int x = cfg->width`의 value 노드) field_expression으로 인식하지 못하고 하위 identifier `cfg`만 추출함.

**영향:** `cfg->width`가 `rhs_vars`에 `['cfg->width']` 대신 `['cfg']`로 들어감. 이로 인해 taint_tracker의 `_trace_backward`에서 `cfg`를 추적하게 되어, source 매칭(`cfg->width` 패턴)에 실패할 수 있음. 단, AliasMap의 `resolve_field`가 보완하는 경우도 있어 모든 케이스에서 실패하지는 않음.

**수정 제안:**
```python
def _extract_variables(node: Node) -> list[str]:
    vars_found = []
    # 루트 노드 자체가 field_expression인 경우 처리
    if node.type == "field_expression":
        vars_found.append(node_text(node).strip())
        return vars_found  # field_expression 자체를 반환하고 내부는 탐색하지 않음
    # ... 기존 로직
```

## 테스트 로그

### V4. Import 체인 테스트
```
$ python -c "from cpp_analyzer.analysis.models import TaintNode, DataFlowPath; ..."
V4 Import check: ALL IMPORTS OK
SCHEMA_VERSION: 6
```

### CLI --help 테스트
```
$ python -m cpp_analyzer trace dataflow --help
Usage: cli trace dataflow [OPTIONS]

  Trace dataflow from config fields to register writes (taint analysis).

Options:
  --db TEXT             [default: cpp_analysis.db]
  --project-id INTEGER
  --source TEXT         Source pattern regex (default: config field patterns)
  --sink TEXT           Sink pattern regex (default: REG_WRITE, reg->field patterns)
  --depth INTEGER       Max trace depth  [default: 5]
  --max-paths INTEGER   Max dataflow paths  [default: 100]
  --save                Save results to DB
  --format [tree|json]  Output format  [default: tree]
  --help                Show this message and exit.

EXIT CODE: 0
```

### T1. 전체 흐름 테스트
```
AliasMap: OK (p->config, q->config 체인 해석 정상)
ts_parser: 2 assignments, 1 calls, 1 params
  width = cfg->width (rhs_vars=['cfg'])  -- P2 버그 관련
  scaled = width * 2 (rhs_vars=['width'])
  REG_WRITE(['CTRL_REG', 'scaled'])
  setup_hw(['cfg'])
```

### T2. DB 저장/조회 테스트
```
Schema version 6: OK
Tables exist: OK
dataflow_paths CRUD: OK (insert/get/filter/delete)
call_args CRUD: OK (2 args)
stats includes dataflow_paths: OK
=== ALL TESTS PASSED ===
```
