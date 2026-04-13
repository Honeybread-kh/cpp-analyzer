/**
 * G2 fixture: pointer-returning handle guarded by IS_ERR, then used as
 * the first arg of a sink accessor. Config taint flows through the sink's
 * value arg (cfg->ctrl), while the handle itself is error-checked.
 */

#include <stdint.h>

typedef uint32_t u32;

#define G2_CTRL_REG 0x10

typedef struct { u32 ctrl; u32 mode; } G2Cfg;

struct g2_dev;
struct g2_regmap;

extern struct g2_regmap *devm_regmap_init(struct g2_dev *dev, u32 cfg);
extern int  IS_ERR(const void *p);
extern long PTR_ERR(const void *p);
extern void regmap_write(struct g2_regmap *rm, u32 reg, u32 val);

int g2_probe(struct g2_dev *dev, G2Cfg *cfg) {
    struct g2_regmap *rm = devm_regmap_init(dev, cfg->mode);
    if (IS_ERR(rm))
        return (int)PTR_ERR(rm);
    regmap_write(rm, G2_CTRL_REG, cfg->ctrl);
    return 0;
}
