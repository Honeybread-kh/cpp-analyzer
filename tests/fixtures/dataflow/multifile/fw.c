#include "include/hw_types.h"
#include "include/hw_regs.h"

/* Layer 1: config → firmware parameters (separate TU). */

void fw_compute(Config* cfg, FwParams* fw) {
    fw->clk_div = cfg->frequency / BASE_CLK;
    fw->timing_val = fw->clk_div - 1;
}
