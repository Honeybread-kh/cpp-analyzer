/**
 * C03 fixture: 3-label goto unwind ladder with an MMIO sink between
 * each stage. Reaching-def of cfg must flow through three staged sinks
 * (regmap_set_bits → trigger_enable → seq_mode) while the error path
 * threads back through `err_c → err_b → err_a` labels in reverse order.
 * Why challenging: B3 only covers a single err label; multi-label
 * cascade forces taint to survive across branch-merged control flow
 * where each stage's success def reaches the next stage's use.
 */

#include <stdint.h>

typedef uint32_t u32;

typedef struct { u32 regs[32]; } Cx3Regs;

typedef struct {
    u32 gp_mode;
    u32 trig_mask;
    u32 seq_mode;
} Cx3Cfg;

typedef struct {
    Cx3Regs *hw;
} Cx3State;

#define CX3_GP_MODE_REG    0x10
#define CX3_TRIG_REG       0x14
#define CX3_SEQ_REG        0x18

extern int regmap_set_bits(u32 reg, u32 val);
extern int cx3_trigger_enable(Cx3State *st, u32 mask);
extern int cx3_seq_mode_enter(Cx3State *st, u32 mode);
extern int cx3_trigger_disable(Cx3State *st);
extern int cx3_busy_output_disable(Cx3State *st);
extern int cx3_unoptimize_message(Cx3State *st);

/* C03: three staged sinks, three unwind labels. */
int cx3_postenable(Cx3State *st, Cx3Cfg *cfg)
{
    int ret;

    ret = regmap_set_bits(CX3_GP_MODE_REG, cfg->gp_mode);
    if (ret)
        goto err_a;

    ret = cx3_trigger_enable(st, cfg->trig_mask);
    if (ret)
        goto err_b;

    ret = cx3_seq_mode_enter(st, cfg->seq_mode);
    if (ret)
        goto err_c;

    return 0;

err_c:
    cx3_trigger_disable(st);
err_b:
    cx3_busy_output_disable(st);
err_a:
    cx3_unoptimize_message(st);
    return ret;
}
