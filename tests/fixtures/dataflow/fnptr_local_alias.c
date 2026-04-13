/**
 * G1 fixture: fnptr copied to a local variable then invoked indirectly.
 * `fp = ops->write; fp(cfg, regs)` must resolve the callee via the
 * existing fnptr-table registration (F3) even when the dispatch site
 * uses a plain identifier rather than the direct array/member expr.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct { u32 freq; u32 mode; } G1Cfg;
typedef struct { u32 regs[8]; } G1Regs;

#define G1_TIMING_REG 0
#define G1_MODE_REG   1

typedef void (*g1_fn)(G1Cfg*, G1Regs*);

static void g1_write_timing(G1Cfg* c, G1Regs* r) { r->regs[G1_TIMING_REG] = c->freq; }
static void g1_write_mode  (G1Cfg* c, G1Regs* r) { r->regs[G1_MODE_REG]   = c->mode; }

enum g1_op { G1_OP_TIMING = 0, G1_OP_MODE = 1, G1_OP_MAX };

static const g1_fn g1_ops[G1_OP_MAX] = {
    [G1_OP_TIMING] = g1_write_timing,
    [G1_OP_MODE]   = g1_write_mode,
};

/* G1: copy fnptr to local, null-check, then call indirectly. */
void g1_dispatch_timing(G1Cfg* cfg, G1Regs* r) {
    g1_fn fp = g1_ops[G1_OP_TIMING];
    if (!fp) return;
    fp(cfg, r);
}

void g1_dispatch_mode(G1Cfg* cfg, G1Regs* r) {
    g1_fn fp = g1_ops[G1_OP_MODE];
    if (!fp) return;
    fp(cfg, r);
}
