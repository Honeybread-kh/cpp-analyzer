/**
 * P5 fixture: multi-callback registration, bitfield sinks, FAM writes.
 */

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
} P5Config;

typedef struct {
    uint32_t regs[64];
} P5HwRegs;

#define P5_TIMING_REG  0x00
#define P5_MODE_REG    0x04

/* (a) multi-callback registration: both cb_timing and cb_mode must be
 *     recognised as reachable from the shared fire point. */
typedef void (*p5_cb_t)(P5HwRegs* r, uint32_t v);

static p5_cb_t g_p5_cbs[4];
static int g_p5_n;

static void cb_timing(P5HwRegs* r, uint32_t v) { r->regs[P5_TIMING_REG] = v; }
static void cb_mode(P5HwRegs* r, uint32_t v)   { r->regs[P5_MODE_REG]   = v; }

void p5_register_cb(p5_cb_t f) { g_p5_cbs[g_p5_n++] = f; }

void p5_fire_cbs(P5HwRegs* r, uint32_t v) {
    for (int i = 0; i < g_p5_n; i++) g_p5_cbs[i](r, v);
}

void p5_multi_cb_init(void) {
    p5_register_cb(cb_timing);
    p5_register_cb(cb_mode);
}

void p5_multi_cb_fire(P5Config* pcfg, P5HwRegs* r) {
    p5_fire_cbs(r, pcfg->frequency);
}

/* (b) bitfield write: taint enters via a bitfield member, then the
 *     packed struct is written out via type-punning. */
typedef struct {
    uint32_t a : 8;
    uint32_t b : 16;
    uint32_t c : 8;
} P5Packed;

void p5_bitfield_write(P5Config* pcfg, P5HwRegs* regs) {
    P5Packed pk = {0};
    pk.b = pcfg->frequency;
    regs->regs[P5_TIMING_REG] = *(uint32_t*)&pk;
}

/* (c) flexible array member: last struct field taints register write. */
typedef struct {
    int n;
    uint32_t data[];
} P5Msg;

void p5_fam_write(P5Config* pcfg, P5Msg* m, P5HwRegs* regs) {
    m->data[0] = pcfg->mode;
    regs->regs[P5_MODE_REG] = m->data[0];
}
