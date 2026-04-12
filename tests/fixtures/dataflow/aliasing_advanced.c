/**
 * P2 fixture: conditional alias (phi), linked-list traversal,
 * dynamic-index struct-array sinks.
 */

#include <stdint.h>

typedef struct {
    int frequency;
    int mode;
    int enable;
} AAConfig;

typedef struct {
    uint32_t regs[64];
} AAHwRegs;

#define AA_TIMING_REG  0x00
#define AA_MODE_REG    0x04
#define AA_CTRL_REG    0x08

/* (a) conditional alias: p resolves to one of {ra, rb} via ternary. */
void cond_alias_write(AAConfig* acfg, AAHwRegs* ra, AAHwRegs* rb, int sel) {
    AAHwRegs* p = sel ? ra : rb;
    p->regs[AA_TIMING_REG] = acfg->frequency;
}

/* (b) linked list: taint flows to every node->regs->regs[...] in a chain. */
typedef struct AANode {
    struct AANode* next;
    AAHwRegs* regs;
} AANode;

void list_walk_write(AAConfig* acfg, AANode* head) {
    for (AANode* n = head; n; n = n->next) {
        n->regs->regs[AA_MODE_REG] = acfg->mode;
    }
}

/* (c) dynamic (non-constant) array index. */
void dyn_index_write(AAConfig* acfg, AAHwRegs** arr, int i) {
    arr[i]->regs[AA_CTRL_REG] = acfg->enable;
}
