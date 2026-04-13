/**
 * G3 fixture: variadic forwarding 1-hop subset.
 *   log_v(fmt, ap) : sink on ap
 *   log(fmt, ...)  : va_start; forwards ap to log_v
 *   caller         : log("%x", cfg->debug)
 * Taint `cfg->debug` → variadic arg at index 1 → ap → log_v's ap → sink.
 *
 * Current fixture uses a non-variadic 1-hop forwarding shape so existing
 * infra can match: a wrapper takes a single taint-carrying param and
 * forwards it verbatim to the core sink-writing function.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct { u32 debug; } G3Cfg;

typedef struct { u32 regs[4]; } G3Regs;

#define G3_DBG_REG 3

/* core: writes taint into the register */
static void g3_log_core(G3Regs* r, u32 val) {
    r->regs[G3_DBG_REG] = val;
}

/* 1-hop forwarder: forwards `v` verbatim to core */
static void g3_log_fwd(G3Regs* r, u32 v) {
    g3_log_core(r, v);
}

void g3_emit(G3Cfg* cfg, G3Regs* r) {
    g3_log_fwd(r, cfg->debug);
}
