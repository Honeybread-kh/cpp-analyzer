/**
 * P3 fixture: C++ virtual dispatch + member function pointer.
 *
 * Exercises callee-resolution across inheritance and pointer-to-member
 * calls that traditional C function-pointer tracking can't handle.
 */

#include <cstdint>

struct CppConfig {
    int frequency;
    int mode;
};

struct CppHwRegs {
    uint32_t regs[64];
};

#define CPP_TIMING_REG  0x00
#define CPP_MODE_REG    0x04

struct Writer {
    virtual ~Writer() = default;
    virtual void write(CppHwRegs* regs, uint32_t v) = 0;
};

struct TimingWriter : Writer {
    void write(CppHwRegs* regs, uint32_t v) override {
        regs->regs[CPP_TIMING_REG] = v;
    }
};

struct ModeWriter : Writer {
    void write(CppHwRegs* regs, uint32_t v) override {
        regs->regs[CPP_MODE_REG] = v;
    }
};

/* Virtual dispatch: caller has only the abstract base pointer. */
void vcall_write(CppConfig* ccfg, CppHwRegs* regs, Writer* w) {
    w->write(regs, ccfg->frequency);
}

/* Member function pointer invocation. */
using WriteMemFn = void (Writer::*)(CppHwRegs*, uint32_t);

void memfn_write(CppConfig* ccfg, CppHwRegs* regs, Writer* w, WriteMemFn fn) {
    (w->*fn)(regs, ccfg->mode);
}
