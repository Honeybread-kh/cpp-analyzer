# Benchmark Report — 2026-04-13 (post P1~P5 evolution)

**Commit:** 2ded336 (main)
**Score:** 97/97 (100.0%)  = vs previous (97/97)
**Pytest:** 60 passed + 1 xfailed (total 61 collected) — 0 failed

No regression. All P1~P5 newly added tests pass.

## Delta (이전 대비)

| 항목 | 이전 (20260413_084047) | 현재 | 변화 |
|------|------|------|------|
| benchmark score | 97/97 | 97/97 | = |
| pct | 100.0% | 100.0% | = |
| benchmark results count | 46 | 46 | = |
| pytest passed | (baseline N/A) | 60 | — |
| pytest xfailed | (baseline N/A) | 1 | — |
| regressions | — | 0 | OK |

> 참고: `_benchmark_report.json`의 `results` 집합(46종 패턴)은 변경되지 않았다. P1~P5 진화로 추가된 5개 테스트 클래스(TestDeepChain, TestAliasingAdvanced, TestCppDispatch, TestIfdefVariants, TestMultiCallback)는 pytest 차원에서 모두 통과하지만 현재 벤치마크 스코어러(`tests/test_dataflow.py::TestBenchmark`)의 집계 대상 46 패턴에는 포함되어 있지 않다. 스코어 유지(100%)의 의미는 "기존 커버리지 무회귀" + "신규 테스트 클래스도 전수 통과"이다.

## 신규 테스트 클래스 결과 (P1~P5)

| 클래스 | 테스트 | 결과 |
|--------|-------|------|
| TestDeepChain (P1) | test_five_hop_param_chain | PASS |
| TestDeepChain (P1) | test_mutual_recursion | PASS |
| TestAliasingAdvanced (P2) | test_cond_alias | PASS |
| TestAliasingAdvanced (P2) | test_linked_list_walk | PASS |
| TestAliasingAdvanced (P2) | test_dynamic_index | PASS |
| TestCppDispatch (P3) | test_virtual_dispatch_timing | PASS |
| TestCppDispatch (P3) | test_virtual_dispatch_mode | PASS |
| TestCppDispatch (P3) | test_member_fn_ptr | XFAIL (예상된 미지원) |
| TestIfdefVariants (P4) | test_ifdef_fast_branch | PASS |
| TestIfdefVariants (P4) | test_ifdef_else_branch | PASS |
| TestIfdefVariants (P4) | test_ifdef_nested_both | PASS |
| TestMultiCallback (P5) | test_multi_cb_timing | PASS |
| TestMultiCallback (P5) | test_multi_cb_mode | PASS |
| TestMultiCallback (P5) | test_bitfield_struct_sink | PASS |
| TestMultiCallback (P5) | test_flexible_array | PASS |

## 카테고리별 합격률 (벤치마크 스코어러 집계 기준, 46 패턴)

### Difficulty
- easy: 8/8 (100%)
- medium: 25/25 (100%)
- hard: 13/13 (100%)

### Requires (전체 전수 통과)
basic 5/5, alias_tracking 1/1, macro_sink 2/2, conditional_tracking 1/1,
compound_assignment 1/1, inter_procedural 2/2, ternary_tracking 1/1,
array_element_tracking 1/1, bitfield_tracking 1/1, global_tracking 1/1,
struct_copy_tracking 1/1, multi_reaching_def 1/1, range_tracking 2/2,
dependency_tracking 2/2, enum_tracking 3/3, ternary_range 1/1, clamp_macro 1/1,
volatile_mmio 2/2, minmax_macro 1/1, union_aliasing 2/2, fnptr_tracking 3/3,
macro_expansion 2/2, ptr_arith_tracking 3/3, callback_tracking 1/1,
cast_tracking 3/3, struct_array_indexing 2/2

## Gap 리스트

벤치마크 스코어러 기준: **0 gap** (all 46 patterns PASS).

pytest 전체 기준: 1 XFAIL (TestCppDispatch::test_member_fn_ptr) — 의도적 미지원 표시.

## 관찰 / 권고

- P1~P5 진화가 벤치마크 점수를 유지하면서 신규 케이스 커버리지를 추가했다 (무회귀).
- 다만 현 스코어러(46 패턴)는 이미 100%에 도달하여 추가 진화의 측정 해상도가 0이다.
  신규 테스트 클래스(TestDeepChain 등)를 `TestBenchmark` 스코어러의 집계 대상에 포함시키는 리팩토링이 필요하다.
  그래야 이후 진화 사이클에서 regression/향상이 숫자로 관찰 가능하다.
- 현 상태로는 implementer 단계로 자동 진행 가능 (regression 없음).
