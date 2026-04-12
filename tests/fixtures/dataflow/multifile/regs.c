#include "include/hw_types.h"
#include "include/hw_regs.h"

/* Layer 2: fw params → hardware registers (separate TU from fw.c). */

void regs_apply_timing(FwParams* fw, HwRegs* regs) {
    regs->regs[TIMING_REG] = fw->timing_val << 8;
}

void regs_direct_mode(Config* cfg, HwRegs* regs) {
    REG_WRITE(regs, MODE_REG, cfg->mode);
}

void regs_threshold(Config* cfg, HwRegs* regs) {
    regs->regs[THRESH_REG] = cfg->threshold;
}
