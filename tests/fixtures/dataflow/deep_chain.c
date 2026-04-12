/**
 * P1 fixture: deep call chain (4~6 hop) + mutual recursion.
 * Stresses _trace_backward recursion depth and memoization.
 *
 * Design: each stage takes a tainted param, stores into a local, and the
 * register write uses that local — forcing the tracker to step through
 * each call frame rather than matching the source literal on the sink RHS.
 */

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
} DeepConfig;

typedef struct {
    uint32_t regs[64];
} DeepHwRegs;

#define DC_TIMING_REG  0x00
#define DC_MODE_REG    0x04

/* ── 5-hop param-propagation chain ────────────────────────── */

static void dc_stage5(DeepHwRegs* regs, uint32_t v5) {
    uint32_t out = v5 << 2;
    regs->regs[DC_TIMING_REG] = out;
}
static void dc_stage4(DeepHwRegs* regs, uint32_t v4) { dc_stage5(regs, v4 | 0x1u); }
static void dc_stage3(DeepHwRegs* regs, uint32_t v3) { dc_stage4(regs, v3 / 2); }
static void dc_stage2(DeepHwRegs* regs, uint32_t v2) { dc_stage3(regs, v2 + 1); }
static void dc_stage1(DeepHwRegs* regs, uint32_t v1) { dc_stage2(regs, v1);     }

void deep_chain_write(DeepConfig* dcfg, DeepHwRegs* dregs) {
    dc_stage1(dregs, dcfg->frequency);
}

/* ── mutual recursion: odd/even, bounded ──────────────────── */

static void recurse_even(DeepHwRegs* regs, uint32_t v, int n);
static void recurse_odd(DeepHwRegs* regs, uint32_t v, int n) {
    if (n == 0) { regs->regs[DC_MODE_REG] = v; return; }
    recurse_even(regs, v + 1, n - 1);
}
static void recurse_even(DeepHwRegs* regs, uint32_t v, int n) {
    if (n == 0) { regs->regs[DC_MODE_REG] = v; return; }
    recurse_odd(regs, v, n - 1);
}

void mutual_recurse_write(DeepConfig* dcfg, DeepHwRegs* dregs) {
    recurse_odd(dregs, dcfg->mode, 3);
}
