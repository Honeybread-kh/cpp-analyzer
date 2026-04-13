/**
 * F1 fixture: kernel-style MMIO accessors. Sink is a function call
 * (writel/iowrite32/regmap_write), not an assignment. Taint must
 * flow from config field to the value argument of the accessor.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct {
    u32 freq;
    u32 mode;
    u32 flags;
} F1Cfg;

typedef struct {
    volatile void *base;
} F1Regs;

#define F1_TIMING_OFF 0x00
#define F1_MODE_OFF   0x04
#define F1_FLAGS_REG  0x08

static inline void writel(u32 val, volatile void *addr) { *(volatile u32*)addr = val; }
static inline void iowrite32(u32 val, volatile void *addr) { *(volatile u32*)addr = val; }
static inline void regmap_write(void* map, u32 reg, u32 val) { (void)map; (void)reg; (void)val; }

void f1_writel_timing(F1Cfg* fcfg, F1Regs* r) {
    writel(fcfg->freq, (char*)r->base + F1_TIMING_OFF);
}

void f1_iowrite32_mode(F1Cfg* fcfg, F1Regs* r) {
    iowrite32(fcfg->mode, (char*)r->base + F1_MODE_OFF);
}

void f1_regmap_flags(F1Cfg* fcfg, void* map) {
    regmap_write(map, F1_FLAGS_REG, fcfg->flags);
}
