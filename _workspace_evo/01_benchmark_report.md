# Benchmark Report — 2026-04-13

**Commit:** e02ff33e (main)
**Score:** 153/153 (100.0%)  ↑ vs previous 97/97
**Status:** NO REGRESSION — all previous PASS items still PASS

## Delta (이전 대비)
| 항목 | 이전 (90122239) | 현재 (e02ff33e) | 변화 |
|------|------|------|------|
| score | 97 | 153 | +56 |
| max_score | 97 | 153 | +56 |
| pct | 100.0% | 100.0% | = |
| total tests | 45 | 65 | +20 |
| regressions | - | 0 | - |
| pytest passed | 60 | 66 | +6 |
| xfailed | 1 | 1 | = |

## 카테고리별 합격률

### Difficulty
- easy: 8/8 (100%)
- medium: 29/29 (100%)
- hard: 29/29 (100%)

### Requires (신규 추가 카테고리)
- deep_call_chain: 1/1
- mutual_recursion: 1/1
- conditional_alias: 1/1
- linked_list_tracking: 1/1
- dynamic_index: 1/1
- cpp_virtual_dispatch: 2/2
- ifdef_both_branches: 3/3
- multi_callback_array: 2/2
- bitfield_typepun: 1/1
- flexible_array_member: 1/1
- **container_of_alias: 2/2** (B.2 구현)
- **goto_reaching_def: 2/2** (B.3 구현)
- **memcpy_bulk_copy: 2/2** (B.1 구현)

기존 26개 requires 카테고리 모두 100% 유지.

## 신규 20 테스트 케이스 (모두 PASS)
A(expected.yaml 확장 14건) + B.1(memcpy 2) + B.2(container_of 2) + B.3(goto unwind 2):
- deep chain 5-hop param propagation, mutual recursion odd/even
- conditional alias ternary pointer, linked list walk taint, dynamic array index sink
- cpp virtual dispatch timing/mode
- ifdef fast-path / else / nested mode variant A
- multi-cb array dispatch timing/mode, bitfield type-pun sink, flexible array member sink
- container_of frequency/mode (B.2)
- goto unwind timing/mode reaching-def (B.3)
- memcpy bulk copy frequency/mode (B.1)

## Gap 리스트
없음. `gaps: []`. 유일한 XFAIL: `test_member_fn_ptr` (C++ member function pointer, expected xfail).

## 결론
A/B.1/B.2/B.3 확장은 regression 없이 전량 PASS. max_score 97→153 확장 달성.
