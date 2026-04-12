/**
 * B1 fixture: struct bulk copy via memcpy propagates taint from the
 * source blob to the destination blob, so subsequent field reads off
 * the destination must resolve back to the original source.
 */

#include <stdint.h>
#include <string.h>

typedef struct {
    int frequency;
    int mode;
} McConfig;

typedef struct {
    uint32_t regs[16];
} McHwRegs;

#define MC_TIMING_REG 0x00
#define MC_MODE_REG   0x04

/* (a) &local ← cfg: entire struct copied, field read later */
void memcpy_bulk_write(McConfig* mcfg, McHwRegs* regs) {
    McConfig local;
    memcpy(&local, mcfg, sizeof(*mcfg));
    regs->regs[MC_TIMING_REG] = local.frequency;
    regs->regs[MC_MODE_REG]   = local.mode;
}
