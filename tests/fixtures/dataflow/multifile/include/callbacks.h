#ifndef CALLBACKS_H
#define CALLBACKS_H

#include "hw_types.h"

typedef void (*evt_cb_t)(HwRegs*, uint32_t);

void cb_register(void);
void cb_fire(Config* cfg, HwRegs* regs);

#endif
