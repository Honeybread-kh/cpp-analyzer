#ifndef HW_REGS_H
#define HW_REGS_H

#define TIMING_REG  0x00
#define MODE_REG    0x04
#define CTRL_REG    0x08
#define THRESH_REG  0x0C

#define BASE_CLK    100

#define REG_WRITE(r, idx, v) (r)->regs[(idx)] = (v)

#endif
