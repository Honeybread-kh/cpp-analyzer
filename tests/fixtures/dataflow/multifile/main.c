#include "include/hw_types.h"
#include "include/callbacks.h"

/* Top-level driver: orchestrates the two-layer pipeline. */

extern void fw_compute(Config* cfg, FwParams* fw);
extern void regs_apply_timing(FwParams* fw, HwRegs* regs);
extern void regs_direct_mode(Config* cfg, HwRegs* regs);
extern void regs_threshold(Config* cfg, HwRegs* regs);

void driver_main(Config* cfg, FwParams* fw, HwRegs* regs) {
    fw_compute(cfg, fw);
    regs_apply_timing(fw, regs);
    regs_direct_mode(cfg, regs);
    regs_threshold(cfg, regs);
    cb_register();
    cb_fire(cfg, regs);
}
