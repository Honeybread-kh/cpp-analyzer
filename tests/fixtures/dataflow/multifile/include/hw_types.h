#ifndef HW_TYPES_H
#define HW_TYPES_H

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
    int enable;
    int threshold;
} Config;

typedef struct {
    int clk_div;
    int timing_val;
} FwParams;

typedef struct {
    uint32_t regs[64];
} HwRegs;

#endif
