/**
 * B2 fixture: container_of/offsetof — recover outer struct from an
 * embedded member pointer. Standard kernel pattern.
 */

#include <stdint.h>
#include <stddef.h>

#ifndef container_of
#define container_of(ptr, type, member) \
    ((type*)((char*)(ptr) - offsetof(type, member)))
#endif

typedef struct {
    int frequency;
    int mode;
} CoCfg;

typedef struct {
    int id;
    CoCfg cfg;
} CoWrapper;

typedef struct {
    uint32_t regs[16];
} CoHwRegs;

#define CO_TIMING_REG 0x00
#define CO_MODE_REG   0x04

void co_recover_write(CoCfg* icfg, CoHwRegs* regs) {
    CoWrapper* w = container_of(icfg, CoWrapper, cfg);
    regs->regs[CO_TIMING_REG] = w->cfg.frequency;
    regs->regs[CO_MODE_REG]   = w->cfg.mode;
}
