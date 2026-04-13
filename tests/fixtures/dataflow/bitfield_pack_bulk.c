/**
 * C01 fixture: 7-field FIELD_PREP bit-pack OR-chained into one register
 * value, then regmap_write sink, followed by memcpy bulk copy of the
 * whole setup struct back into a per-slot cache.
 * Why challenging: taint must fan out from 7 distinct cfg fields into a
 * single packed scalar, survive a bitfield shift/mask macro, reach the
 * regmap_write sink, AND be recognised again after a sizeof()-sized
 * memcpy replicates the source struct.
 */

#include <stdint.h>

typedef uint32_t u32;

#define CX1_FIELD_PREP(mask, val) (((val) << __builtin_ctz(mask)) & (mask))

#define CX1_IOUT0_MASK    0x00000003u
#define CX1_IOUT1_MASK    0x0000000Cu
#define CX1_BURNOUT_MASK  0x00000030u
#define CX1_REFBUFP_MASK  0x00000040u
#define CX1_REFBUFM_MASK  0x00000080u
#define CX1_REFSEL_MASK   0x00000300u
#define CX1_PGA_MASK      0x00007000u

#define CX1_CONFIG_REG(slot)  (0x20 + (slot))
#define CX1_FILTER_REG(slot)  (0x40 + (slot))

typedef struct {
    u32 iout0_val;
    u32 iout1_val;
    u32 burnout;
    u32 ref_bufp;
    u32 ref_bufm;
    u32 ref_sel;
    u32 pga;
    u32 filter_type;
    u32 fs;
} Cx1Cfg;

typedef struct {
    Cx1Cfg setup;
} Cx1Slot;

typedef struct {
    Cx1Slot slots[4];
} Cx1State;

/* external sink — kept opaque on purpose */
extern int regmap_write(u32 reg, u32 val);

/* C01: fan-out pack + regmap_write sink + memcpy bulk replicate. */
int cx1_apply_setup(Cx1State *st, int slot, Cx1Cfg *cfg)
{
    u32 val;

    val  = CX1_FIELD_PREP(CX1_IOUT0_MASK,   cfg->iout0_val);
    val |= CX1_FIELD_PREP(CX1_IOUT1_MASK,   cfg->iout1_val);
    val |= CX1_FIELD_PREP(CX1_BURNOUT_MASK, cfg->burnout);
    val |= CX1_FIELD_PREP(CX1_REFBUFP_MASK, cfg->ref_bufp);
    val |= CX1_FIELD_PREP(CX1_REFBUFM_MASK, cfg->ref_bufm);
    val |= CX1_FIELD_PREP(CX1_REFSEL_MASK,  cfg->ref_sel);
    val |= CX1_FIELD_PREP(CX1_PGA_MASK,     cfg->pga);

    regmap_write(CX1_CONFIG_REG(slot), val);

    val = (cfg->filter_type << 16) | cfg->fs;
    regmap_write(CX1_FILTER_REG(slot), val);

    /* bulk replicate the whole source struct into per-slot cache */
    Cx1Cfg *dst = &st->slots[slot].setup;
    __builtin_memcpy(dst, cfg, sizeof(*cfg));
    return 0;
}
