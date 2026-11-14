@ live120: logging trampoline for the LV display callback record (heap 0x419300, slot 0 = fc12898b).
@ Records the call count, r0-r3 and the first 24 stack arguments of the last call, then jumps to
@ the original callback with every register and the stack untouched.
@ Layout: +0 code, +0x80 literal ORIG, +0x84 literal LOG, LOG = +0x100: [0] count, [1..4] r0-r3, [5..28] stack.
    .syntax unified
    .thumb
    .global _start
_start:
    push    {r0-r7, r8, lr}          @ 40 bytes, 8-aligned
    ldr     r4, lit_log
    ldr     r5, [r4]
    adds    r5, #1
    str     r5, [r4]
    str     r0, [r4, #4]
    str     r1, [r4, #8]
    str     r2, [r4, #12]
    str     r3, [r4, #16]
    add     r6, sp, #40              @ caller's stack arguments
    adds    r4, #20
    movs    r7, #24
1:  ldr     r5, [r6], #4
    str     r5, [r4], #4
    subs    r7, #1
    bne     1b
    pop     {r0-r7, r8, lr}
    ldr.w   pc, lit_orig
    .balign 4
    .org 0x80
lit_orig: .word 0xfc12898b
lit_log:  .word 0
