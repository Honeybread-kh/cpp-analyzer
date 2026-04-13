/**
 * F3 fixture: static fnptr ops table indexed by enum constant. Taint
 * dispatch via `ops[OP_X](cfg, regs)` should resolve to the specific
 * callee bound to OP_X (constant folding), not fan-out to all entries.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct { u32 freq; u32 mode; } F3Cfg;
typedef struct { u32 regs[8]; } F3Regs;

#define F3_TIMING_REG 0
#define F3_MODE_REG   1
#define F3_CTRL_REG   2

enum f3_op { F3_OP_TIMING = 0, F3_OP_MODE = 1, F3_OP_CTRL = 2, F3_OP_MAX };

static void f3_do_timing(F3Cfg* c, F3Regs* r) { r->regs[F3_TIMING_REG] = c->freq; }
static void f3_do_mode  (F3Cfg* c, F3Regs* r) { r->regs[F3_MODE_REG]   = c->mode; }
static void f3_do_ctrl  (F3Cfg* c, F3Regs* r) { r->regs[F3_CTRL_REG]   = c->freq | c->mode; }

typedef void (*f3_fn)(F3Cfg*, F3Regs*);

static const f3_fn f3_ops[F3_OP_MAX] = {
    [F3_OP_TIMING] = f3_do_timing,
    [F3_OP_MODE]   = f3_do_mode,
    [F3_OP_CTRL]   = f3_do_ctrl,
};

void f3_dispatch_timing(F3Cfg* cfg, F3Regs* r) { f3_ops[F3_OP_TIMING](cfg, r); }
void f3_dispatch_mode(F3Cfg* cfg, F3Regs* r)   { f3_ops[F3_OP_MODE](cfg, r); }
void f3_dispatch_dynamic(enum f3_op op, F3Cfg* cfg, F3Regs* r) { f3_ops[op](cfg, r); }
