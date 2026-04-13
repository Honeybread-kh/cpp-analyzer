/**
 * C02 fixture: designated-init function-pointer dispatch table bound to
 * a struct pointer (`st->ops->write(...)` topology).
 * Why challenging: F3 indexes an fnptr array by enum; here the table is
 * a struct whose fields are fn-ptrs assigned by designated init. The
 * dispatch site traverses a pointer-to-struct-of-ops to reach the sink,
 * so F2 (designated value init) and F3 (array index) are both insufficient.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct { u32 regs[16]; } Cx2Regs;

typedef struct {
    u32 ctrl;
    u32 sample;
} Cx2Cfg;

#define CX2_CTRL_REG    0
#define CX2_SAMPLE_REG  1

struct cx2_ops;

typedef struct {
    Cx2Regs *hw;
    const struct cx2_ops *ops;
} Cx2State;

struct cx2_ops {
    void (*write)(Cx2State *st, u32 reg, u32 val);
    void (*setup)(Cx2State *st, Cx2Cfg *cfg);
};

static void cx2_mmio_write(Cx2State *st, u32 reg, u32 val)
{
    st->hw->regs[reg] = val;
}

static void cx2_mmio_setup(Cx2State *st, Cx2Cfg *cfg)
{
    /* taint flows through the dispatch into the concrete sink */
    st->ops->write(st, CX2_CTRL_REG,   cfg->ctrl);
    st->ops->write(st, CX2_SAMPLE_REG, cfg->sample);
}

static const struct cx2_ops cx2_mmio_ops = {
    .write = cx2_mmio_write,
    .setup = cx2_mmio_setup,
};

/* C02: caller dispatches via struct-ops pointer. */
void cx2_configure(Cx2State *st, Cx2Cfg *cfg)
{
    st->ops = &cx2_mmio_ops;
    st->ops->setup(st, cfg);
}
