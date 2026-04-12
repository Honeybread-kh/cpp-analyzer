# Benchmark Report -- 2026-04-12T15:33:49Z

**Commit:** 9e0fb78a9a3316b58c83f3640c5186885cfb02ce (main)
**Score:** 45/45 (100.0%) = vs previous (100.0%)

No regression detected.

## Delta (이전 대비)

| 항목 | 이전 | 현재 | 변화 |
|------|------|------|------|
| 점수 | 21/21 | 45/45 | +24 (테스트 케이스 확장) |
| 퍼센트 | 100.0% | 100.0% | = |
| 발견 경로 수 | 14 | 29 | +15 |
| 테스트 케이스 수 | 12 | 25 | +13 (신규 추가) |

### 신규 추가된 테스트 케이스 (13건)

| 이름 | 난이도 | requires |
|------|--------|----------|
| ternary operator tracking | medium | ternary_tracking |
| array element constant index | medium | array_element_tracking |
| bitfield shift+mask packing | medium | bitfield_tracking |
| global variable relay | hard | global_tracking |
| struct copy field access | medium | struct_copy_tracking |
| phi-node multiple reaching defs | medium | multi_reaching_def |
| range clamp frequency | medium | range_tracking |
| range saturate threshold | medium | range_tracking |
| dependency freq+mode to ctrl | medium | dependency_tracking |
| dependency enable gates frequency | medium | dependency_tracking |
| enum config op_mode | easy | enum_tracking |
| enum config clk_src | easy | enum_tracking |
| enum range power_level | easy | enum_tracking |

## 카테고리별 합격률

### Difficulty

- easy: 8/8 (100%)
- medium: 14/14 (100%)
- hard: 3/3 (100%)

### Requires

- basic: 5/5 (100%)
- alias_tracking: 1/1 (100%)
- macro_sink: 2/2 (100%)
- conditional_tracking: 1/1 (100%)
- compound_assignment: 1/1 (100%)
- inter_procedural: 2/2 (100%)
- ternary_tracking: 1/1 (100%)
- array_element_tracking: 1/1 (100%)
- bitfield_tracking: 1/1 (100%)
- global_tracking: 1/1 (100%)
- struct_copy_tracking: 1/1 (100%)
- multi_reaching_def: 1/1 (100%)
- range_tracking: 2/2 (100%)
- dependency_tracking: 2/2 (100%)
- enum_tracking: 3/3 (100%)

## Gap 리스트

(없음 -- 전체 PASS)
