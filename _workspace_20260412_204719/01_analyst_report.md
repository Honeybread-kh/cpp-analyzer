# Analyst Report — Gap 1 구현 (evolution 위임)

## 컨텍스트
이 보고서는 evolution 하네스의 reasoner가 이미 코드 수준 분석을 완료한 작업을 대상으로 한다. 전체 상세 제안은 `_workspace_evo/02_reasoner_proposal.md`의 "Gap 1" 섹션 참조. 본 문서는 developer가 즉시 구현에 착수할 수 있도록 요점만 정리한다.

## 목표
`cpp-analyzer`의 `_trace_backward`가 함수 호출 반환값을 통한 taint 전파를 지원하도록 확장. multi-hop 패턴(`config → compute_divider → compute_timing → reg`)에서 step의 `function` 필드에 callee 이름이 기록되어야 테스트 PASS.

## 영향받는 파일
| 파일 | 변경 종류 |
|------|----------|
| `cpp_analyzer/analysis/ts_parser.py` | assignment dict에 `rhs_call` 필드 추가, 신규 함수 `extract_function_returns` |
| `cpp_analyzer/analysis/taint_tracker.py` | `_load_all_files`에 `_file_returns` 캐시 채움, `_trace_backward`에 callee 잠수 분기 추가 |

DB 스키마 변경 없음. CLI/MCP 인터페이스 변경 없음.

## 참고할 기존 코드 패턴
- `ts_parser.py::extract_all_assignments` (~L570-) — list[dict] 반환, walk_type + node_text 패턴. 신규 `extract_function_returns`도 같은 스타일로 작성.
- `ts_parser.py::_extract_variables` (L660-690) — call_expression의 함수 이름을 제외하는 로직 (L684-687) **유지**. callee 정보는 반드시 `rhs_call` 별도 필드로만 보존.
- `taint_tracker.py::_load_all_files` (~L190-) — 파일 순회 루프에서 캐시 빌드. 여기에 `extract_function_returns` 호출 1줄 추가.
- `taint_tracker.py::_trace_backward` (~L260-380) — reaching def 루프가 현재 `rhs_vars`만 따라간다. 루프 맨 앞에 `rhs_call` 체크 분기 삽입.

## 의존 관계 및 순서
1. `ts_parser.py` 먼저 수정 — 다운스트림에서 쓸 데이터 구조 먼저 확정
2. `taint_tracker.py::_load_all_files`에서 캐시 채우기
3. `taint_tracker.py::_trace_backward`에 분기 추가
4. pytest 실행해 multi-hop이 PASS 되는지 확인
5. 전체 테스트 19/21 → 20/21 이상 유지 확인

## 엣지 케이스 주의사항
- **call_expression이 중첩된 경우** (`f(g(x))`): 가장 바깥 callee(`f`)만 `rhs_call`에 저장. 더 깊은 잠수는 재귀로 자연스레 해결됨
- **`rhs_call`이 None**인 기존 모든 assignment는 영향 없음 (conditional, alias, macro, compound 모두 해당)
- **재귀 무한루프**: `visited` set에 기존 `(func, var)` 튜플이 이미 있으므로 callee 잠수도 동일 방어 적용
- **callee가 `_func_to_file`에 없는 경우** (외부 라이브러리 함수 등): 분기를 건너뛰고 기존 rhs_vars 루프로 fallback

## 성공 기준
- `uv run pytest tests/test_dataflow.py -v` 실행 시:
  - multi-hop 테스트 PASS 전환
  - 기존 통과 테스트(easy 5 + medium 5 + 기타 = 9 passed) 모두 유지
  - xfailed 개수 감소 (2 → 1 또는 0)
  - 최소 점수: 16/21 (+1), 이상적으로는 multi-hop만 1건 해결 시 16/21

## 비권장 (reasoner가 명시)
- `_extract_variables`에 callee 식별자를 다시 포함시키지 말 것
- DB 스키마 변경 금지
- `_is_param` 완화 금지
- `taint_tracker.py` 전체 재작성 금지 — 부분 확장만
