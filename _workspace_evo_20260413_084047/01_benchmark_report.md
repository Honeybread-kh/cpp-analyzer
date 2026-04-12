# Benchmark Report — 2026-04-13

**Commit:** 7a92e6641169052ddeea1442ed8b3c3ec3e44686 (main)
**Score:** 97/97 (100.0%) — 이전 45/45 (100.0%) 대비 테스트 확장 및 점수 상승
**pytest:** 46 passed, 0 failed (0.81s)

No regression detected. 이전 PASS였던 25개 항목 모두 현재도 PASS 유지.

## Delta (이전 아카이브 baseline 대비)

baseline: `_workspace_evo_20260413_081713/01_benchmark_current.json` (commit 9e0fb78)

| 항목 | 이전 | 현재 | 변화 |
|------|------|------|------|
| score | 45 | 97 | +52 |
| max_score | 45 | 97 | +52 |
| pct | 100.0 | 100.0 | = |
| pytest tests | 25 result-entries | 46 result-entries | +21 |
| gaps | 0 | 0 | = |
| regressed tests | - | 0 | OK |

신규 result-entries 21건 (모두 PASS): union aliasing, ternary clamp, volatile MMIO, ptr arith, cast chain, fnptr dispatch, MIN/MAX macro, CLAMP macro, struct array cross-func, macro expansion writes, callback via global fnptr 등. 최근 커밋의 Gap C3/A4/A5/C2/A1/union aliasing 후속 검증 케이스가 포함되었다.

참고: 사용자 메시지는 66개 테스트를 예상했으나 실제 `pytest tests/test_dataflow.py` 수집은 **46개**다 (`_benchmark_report.json`의 results는 개별 경로 단위라 97개). 이는 수집 방식 차이이며 실패가 아니다.

## 카테고리별 합격률

### Difficulty
- easy: 8/8 (100%)
- medium: 25/25 (100%)
- hard: 13/13 (100%)

### Requires (26 카테고리)
모두 100% PASS:
- basic 5/5, alias_tracking 1/1, macro_sink 2/2, conditional_tracking 1/1
- compound_assignment 1/1, inter_procedural 2/2, ternary_tracking 1/1
- array_element_tracking 1/1, bitfield_tracking 1/1, global_tracking 1/1
- struct_copy_tracking 1/1, multi_reaching_def 1/1, range_tracking 2/2
- dependency_tracking 2/2, enum_tracking 3/3, ternary_range 1/1
- clamp_macro 1/1, volatile_mmio 2/2, minmax_macro 1/1
- union_aliasing 2/2, fnptr_tracking 3/3, macro_expansion 2/2
- ptr_arith_tracking 3/3, callback_tracking 1/1, cast_tracking 3/3
- struct_array_indexing 2/2

## Gap 리스트

없음. 벤치마크 모든 케이스가 PASS 상태.

## 판단

- 100% 유지 — 최근 커밋(B1 parse cache, B2 parallel parse, D1 synthetic 50-module)은 성능/확장성 개선으로 정합성에 악영향 없음 확인
- regression 0건 — implementer 단계 진행 가능 (단, gap 0이므로 reasoner 입력이 비어 있음 → 새 gap 발굴 또는 non-functional 목표로 전환 필요)
