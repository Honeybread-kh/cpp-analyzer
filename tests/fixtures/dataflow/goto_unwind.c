/**
 * B3 fixture: goto-based error unwind. The sink is behind a label that
 * is reached both on the happy path and on an early-error `goto out`.
 * Reaching-def analysis must keep the real assignment (v = ucfg->...)
 * as a candidate source, not only the v=0 initializer.
 */

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
} UnwindConfig;

typedef struct {
    uint32_t regs[16];
} UnwindHwRegs;

#define UN_TIMING_REG 0x00
#define UN_MODE_REG   0x04

int unwind_write_timing(UnwindConfig* ucfg, UnwindHwRegs* regs) {
    uint32_t v = 0;
    if (!ucfg) goto out;
    v = ucfg->frequency;
out:
    regs->regs[UN_TIMING_REG] = v;
    return 0;
}

int unwind_write_mode(UnwindConfig* ucfg, UnwindHwRegs* regs) {
    uint32_t w = 0;
    if (!regs) goto fail;
    w = ucfg->mode;
    goto done;
fail:
    return -1;
done:
    regs->regs[UN_MODE_REG] = w;
    return 0;
}
