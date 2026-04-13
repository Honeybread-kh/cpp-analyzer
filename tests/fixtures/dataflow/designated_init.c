/**
 * F2 fixture: C99 designated initializer. Taint enters through a
 * compound literal or a static profile table's field, then flows
 * through a function argument to a register write.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct {
    u32 freq;
    u32 mode;
    u32 flags;
} F2Cfg;

typedef struct {
    u32 regs[8];
} F2Regs;

#define F2_TIMING_REG 0
#define F2_MODE_REG   1
#define F2_FLAGS_REG  2

/* Case A: callee reads field of a by-value struct passed in. */
void f2_apply(F2Cfg c, F2Regs* r) {
    r->regs[F2_TIMING_REG] = c.freq;
    r->regs[F2_MODE_REG]   = c.mode;
    r->regs[F2_FLAGS_REG]  = c.flags;
}

/* Case A entry: compound literal at the call site. */
typedef struct { u32 frequency; u32 mode; u32 flags; } F2Outer;

void f2_compound_entry(F2Outer* cfg, F2Regs* r) {
    f2_apply((F2Cfg){ .freq = cfg->frequency, .mode = cfg->mode, .flags = cfg->flags }, r);
}

/* Case B: static profile table with designated-init entries. */
static const F2Cfg f2_profiles[] = {
    [0] = { .freq = 100, .mode = 1, .flags = 0 },
    [1] = { .freq = 200, .mode = 2, .flags = 1 },
};

void f2_profile_entry(int i, F2Regs* r) {
    f2_apply(f2_profiles[i], r);
}
