/**
 * P4 fixture: #ifdef-guarded sinks. Both branches must be discoverable
 * via tree-sitter (which parses preprocessor-neutrally), not just the
 * branch the libclang driver happened to select.
 */

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
} IfConfig;

typedef struct {
    uint32_t regs[64];
} IfHwRegs;

#define IF_TIMING_REG  0x00
#define IF_MODE_REG    0x04
#define IF_FAST_REG    0x08

void ifdef_write(IfConfig* icfg, IfHwRegs* regs) {
#ifdef USE_FAST_PATH
    regs->regs[IF_FAST_REG] = icfg->frequency << 1;
#else
    regs->regs[IF_TIMING_REG] = icfg->frequency;
#endif
}

/* Nested: both the #if and #else write a sink of a different flavor. */
void ifdef_nested_write(IfConfig* icfg, IfHwRegs* regs) {
#if defined(MODE_VARIANT_A)
    regs->regs[IF_MODE_REG] = icfg->mode;
#else
    regs->regs[IF_MODE_REG] = icfg->mode | 0x80u;
#endif
}
