/**
 * Dataflow benchmark: HW modeling project simulation.
 * Tests config → FW → register propagation patterns.
 */

#include <stdint.h>

/* ── structs ─────────────────────────────────────── */

typedef struct {
    int frequency;
    int mode;
    int threshold;
    int enable;
    int width;
    int height;
} Config;

typedef struct {
    int clk_div;
    int timing_val;
    int processed_mode;
} FwParams;

typedef struct {
    uint32_t regs[64];
} HwRegs;

/* ── register offsets ──────────────────────────────── */

#define TIMING_REG    0x00
#define MODE_REG      0x04
#define CTRL_REG      0x08
#define THRESH_REG    0x0C
#define DIM_REG       0x10

#define BASE_CLK      100

/* ── layer 1: config → FW params ─────────────────── */

void config_to_fw(Config* cfg, FwParams* fw) {
    fw->clk_div = cfg->frequency / BASE_CLK;
    fw->timing_val = fw->clk_div - 1;
    fw->processed_mode = cfg->mode | (cfg->enable << 16);
}

/* ── layer 2: FW params → HW registers ──────────── */

void fw_to_hw(FwParams* fw, HwRegs* regs) {
    regs->regs[TIMING_REG] = fw->timing_val << 8;
    regs->regs[MODE_REG] = fw->processed_mode;
}

/* ── direct config → register (single function) ──── */

void direct_config_write(Config* cfg, HwRegs* regs) {
    regs->regs[THRESH_REG] = cfg->threshold;
    regs->regs[DIM_REG] = cfg->width | (cfg->height << 16);
}

/* ── pointer alias pattern ───────────────────────── */

void alias_write(Config* cfg) {
    HwRegs* hw = get_hw_regs();
    HwRegs* r = hw;
    r->regs[CTRL_REG] = cfg->enable;
}

/* ── macro-based register write ──────────────────── */

#define REG_WRITE(reg, val)  (*(volatile uint32_t*)(reg) = (val))

void macro_reg_write(Config* cfg) {
    REG_WRITE(TIMING_REG, cfg->frequency);
    REG_WRITE(MODE_REG, cfg->mode);
}

/* ── multi-hop: config → intermediate → intermediate → reg ── */

static int compute_divider(int freq) {
    return freq / BASE_CLK;
}

static int compute_timing(int divider) {
    return divider - 1;
}

void multi_hop_write(Config* cfg, HwRegs* regs) {
    int div = compute_divider(cfg->frequency);
    int timing = compute_timing(div);
    regs->regs[TIMING_REG] = timing << 8;
}

/* ── conditional register write ──────────────────── */

void conditional_write(Config* cfg, HwRegs* regs) {
    if (cfg->enable) {
        regs->regs[CTRL_REG] = cfg->mode;
    } else {
        regs->regs[CTRL_REG] = 0;
    }
}

/* ── compound assignment ─────────────────────────── */

void compound_write(Config* cfg, HwRegs* regs) {
    uint32_t val = 0;
    val |= cfg->mode;
    val |= (cfg->threshold << 8);
    regs->regs[CTRL_REG] = val;
}

/* ── ternary operator ────────────────────────────── */

void ternary_write(Config* cfg, HwRegs* regs) {
    uint32_t val = cfg->enable ? cfg->frequency : 0;
    regs->regs[TIMING_REG] = val;
}

/* ── array element (constant index) ──────────────── */

void array_write(Config* cfg, HwRegs* regs) {
    uint32_t params[4];
    params[0] = cfg->frequency;
    params[1] = cfg->mode;
    regs->regs[TIMING_REG] = params[0];
    regs->regs[MODE_REG] = params[1];
}

/* ── bitfield shift+mask packing ─────────────────── */

void bitfield_write(Config* cfg, HwRegs* regs) {
    uint32_t reg_val = (cfg->mode & 0xFF) | ((cfg->frequency & 0xFFF) << 8) | ((cfg->enable & 0x1) << 20);
    regs->regs[CTRL_REG] = reg_val;
}

/* ── global variable relay ───────────────────────── */

static int g_cached_freq;

void cache_config(Config* cfg) {
    g_cached_freq = cfg->frequency;
}

void apply_cached(HwRegs* regs) {
    regs->regs[TIMING_REG] = g_cached_freq;
}

/* ── struct copy (value semantics) ───────────────── */

void struct_copy_write(Config* cfg, HwRegs* regs) {
    Config local_cfg = *cfg;
    regs->regs[THRESH_REG] = local_cfg.threshold;
}

/* ── phi-node: multiple reaching defs ────────────── */

void phi_write(Config* cfg, HwRegs* regs) {
    uint32_t val;
    if (cfg->enable) {
        val = cfg->frequency;
    } else {
        val = cfg->threshold;
    }
    regs->regs[TIMING_REG] = val;
}

/* ── range constraints: clamp/saturate ──────────── */

#define MIN_FREQ     100
#define MAX_FREQ    1000
#define MAX_THRESHOLD 255

void range_checked_write(Config* cfg, HwRegs* regs) {
    int freq = cfg->frequency;
    if (freq < MIN_FREQ) freq = MIN_FREQ;
    if (freq > MAX_FREQ) freq = MAX_FREQ;

    int thresh = cfg->threshold;
    if (thresh > MAX_THRESHOLD) thresh = MAX_THRESHOLD;

    regs->regs[TIMING_REG] = freq;
    regs->regs[THRESH_REG] = thresh;
}

/* ── enum types ─────────────────────────────────────── */

typedef enum { MODE_LOW = 0, MODE_MED = 1, MODE_HIGH = 2 } OpMode;
enum ClkSource { CLK_INT = 0, CLK_EXT = 1, CLK_PLL = 2 };

typedef struct {
    OpMode op_mode;
    enum ClkSource clk_src;
    int power_level;
} ExtConfig;

void enum_config_write(ExtConfig* ecfg, HwRegs* regs) {
    regs->regs[MODE_REG] = ecfg->op_mode;
    regs->regs[CTRL_REG] = ecfg->clk_src;
}

#define MIN_POWER  0
#define MAX_POWER  100

void enum_range_write(ExtConfig* ecfg, HwRegs* regs) {
    int pwr = ecfg->power_level;
    if (pwr < MIN_POWER) pwr = MIN_POWER;
    if (pwr > MAX_POWER) pwr = MAX_POWER;
    regs->regs[THRESH_REG] = pwr;
}

/* ── range patterns: ternary clamp and CLAMP macro ── */

#define CLAMP(x, lo, hi)  ((x) < (lo) ? (lo) : ((x) > (hi) ? (hi) : (x)))

void ternary_clamp_write(Config* cfg, HwRegs* regs) {
    int freq = cfg->frequency;
    freq = (freq > MAX_FREQ) ? MAX_FREQ : freq;
    freq = (freq < MIN_FREQ) ? MIN_FREQ : freq;
    regs->regs[TIMING_REG] = freq;
}

void clamp_macro_write(Config* cfg, HwRegs* regs) {
    int thresh = CLAMP(cfg->threshold, 0, MAX_THRESHOLD);
    regs->regs[THRESH_REG] = thresh;
}

/* ── volatile MMIO direct write (no macro) ──────────── */

#define HW_BASE 0x40001000

void volatile_mmio_write(Config* cfg) {
    *(volatile uint32_t*)(HW_BASE + 0x00) = cfg->frequency;
    *(volatile uint32_t*)(HW_BASE + 0x04) = cfg->mode;
}

/* ── dependency: multiple config fields → same reg ── */

void dependent_write(Config* cfg, HwRegs* regs) {
    /* frequency and mode both contribute to CTRL_REG */
    uint32_t ctrl = (cfg->frequency / BASE_CLK) | (cfg->mode << 16);
    regs->regs[CTRL_REG] = ctrl;

    /* enable gates whether timing is written */
    if (cfg->enable) {
        regs->regs[TIMING_REG] = cfg->frequency;
    }
}
