# Benchmark Report — 2026-04-11 (initial run)

**Commit:** b605e83c34 (main)
**Score:** 15/21 (71.4%) — baseline 없음 (초기 실행)
**Total paths found:** 11
**Pytest:** 9 passed, 2 xfailed in 1.94s

> 초기 실행 — regression 감지 대상 없음 (`01_benchmark_before.json` 부재).

## Delta
baseline 없음 — 다음 실행부터 비교 가능.

## 카테고리별 합격률

### Difficulty
- easy: 5/5 (100%)
- medium: 5/5 (100%)
- hard: 0/2 (0%)  ← 주 gap

### Requires
- basic: 5/5 (100%)
- alias_tracking: 1/1 (100%)
- macro_sink: 2/2 (100%)
- conditional_tracking: 1/1 (100%)
- compound_assignment: 1/1 (100%)
- inter_procedural: 0/2 (0%)  ← 주 gap

## Gap 리스트
1. multi-hop: config -> divider -> timing -> reg (hard, inter_procedural)
2. two-layer: config -> fw -> hw register (hard, inter_procedural)

## 특이사항
- 두 hard 케이스 모두 `inter_procedural` taint 전파 미구현이 단일 원인으로 보임
- easy/medium 카테고리는 이미 100% — 추가 개선 여지는 hard 카테고리에 집중되어야 함
- 결정적 실행 확인: pytest 옵션에 random/seed 플래그 없음
