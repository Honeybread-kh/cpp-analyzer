# Benchmark Report -- 2026-04-12T05:19:33Z

**Commit:** 417f656d (`main`)
**Score:** 21/21 (100.0%)  +6 vs previous (15/21 -> 21/21)

## Delta (previous comparison)

| Item | Previous | Current | Change |
|------|----------|---------|--------|
| Score | 15/21 | 21/21 | **+6** |
| Pct | 71.4% | 100.0% | **+28.6pp** |
| Paths found | 11 | 14 | +3 |
| Gaps | 2 | 0 | -2 |

### Newly passing tests
| Test | Difficulty | Requires |
|------|-----------|----------|
| multi-hop: config -> divider -> timing -> reg | hard | inter_procedural |
| two-layer: config -> fw -> hw register | hard | inter_procedural |

### Regressions
None.

## Category pass rates

### Difficulty
| Difficulty | Previous | Current |
|-----------|----------|---------|
| easy | 5/5 (100%) | 5/5 (100%) |
| medium | 5/5 (100%) | 5/5 (100%) |
| hard | 0/2 (0%) | 2/2 (100%) |

### Requires
| Requires | Previous | Current |
|----------|----------|---------|
| basic | 5/5 (100%) | 5/5 (100%) |
| alias_tracking | 1/1 (100%) | 1/1 (100%) |
| macro_sink | 2/2 (100%) | 2/2 (100%) |
| conditional_tracking | 1/1 (100%) | 1/1 (100%) |
| compound_assignment | 1/1 (100%) | 1/1 (100%) |
| inter_procedural | 0/2 (0%) | 2/2 (100%) |

## Gap list

No gaps remaining. All 12 test cases pass.
