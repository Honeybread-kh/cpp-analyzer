#include "include/hw_types.h"
#include "include/hw_regs.h"
#include "include/callbacks.h"

/* Callback registered in this TU, fired from Config data. */

static void handle_enable(HwRegs* regs, uint32_t val) {
    regs->regs[CTRL_REG] = val;
}

static evt_cb_t g_cb;

void cb_register(void) {
    g_cb = handle_enable;
}

void cb_fire(Config* cfg, HwRegs* regs) {
    g_cb(regs, cfg->enable);
}
