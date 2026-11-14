@ siohook2.S - RAM hook for *(0x9b50) with a CMOS register rewrite table.
@ Position-independent Thumb-2 blob, injected over USB (m10sio.py v2).
@
@ Same logging ring as v1, plus: for channel 6 (CMOS) frames, each of the
@ 10 registers (reg = word>>12 & 0xf) can be overridden in place before the
@ frame is sent to the sensor.  The override is applied to the caller's
@ buffer under cpsid i, so Canon's RAM shadow (0x2cca8) is untouched and the
@ patch reverts the instant the table is cleared.  ML's cmos_write approach.
@
@ Layout (offsets from blob base):
@   0x000  poke32(addr,val): atomic store, returns old
@   0x010  hook
@   0x100  header: 'SIO2', idx, orig, chanmask, nent-1, over_en, over_hits, ...
@   0x140  cmos[16]: per-register override; bit16 enable, bits0-11 value
@   0x180  ring entries, 64 bytes each (same as v1)
        .syntax unified
        .thumb
        .text
        .global blob
blob:
poke32:                         @ 0x000
        ldr     r2, [r0]
        str     r1, [r0]
        dsb
        mov     r0, r2
        bx      lr
        .balign 16
hook:                           @ 0x010
        push    {r4-r7, lr}
        adr     r4, hdr
        @ --- CMOS register override (channel 6 only) ---
        ldr     r5, [r0]                @ channel
        cmp     r5, #6
        bne     log
        cmp     r2, #16
        bne     log
        ldr     r6, [r4, #20]           @ over_en
        cbz     r6, log
        mrs     r3, apsr
        cpsid   i
        ldr     r6, [r1]                @ frame word (reg<<12 | val)
        ubfx    r7, r6, #12, #4         @ reg 0..15
        add     r5, r4, #0x40           @ cmos table base (0x140)
        ldr     r5, [r5, r7, lsl #2]
        lsls    r12, r5, #15            @ test bit16 (enable) -> N
        bpl     1f
        bfi     r6, r5, #0, #12         @ replace low 12 bits with table value
        str     r6, [r1]
        ldr     r5, [r4, #24]
        adds    r5, #1
        str     r5, [r4, #24]           @ over_hits
1:
        tst     r3, #0x80
        bne     log
        cpsie   i
log:
        ldr     r5, [r0]                @ channel
        ldr     r6, [r4, #12]           @ channel mask
        lsr     r6, r6, r5
        lsls    r6, r6, #31
        beq     out
        mrs     r5, apsr
        cpsid   i
        ldr     r6, [r4, #4]
        adds    r7, r6, #1
        str     r7, [r4, #4]
        msr     apsr_nzcvq, r5
        ldr     r7, [r4, #16]           @ nent - 1
        ands    r6, r6, r7
        add     r6, r4, r6, lsl #6
        add     r6, #0x80               @ entries at 0x180
        ldr     r7, usec_reg
        ldr     r7, [r7]
        str     r7, [r6, #0]
        ldr     r7, [r0]
        str     r7, [r6, #4]
        ldr     r7, [r0, #4]
        str     r7, [r6, #8]
        str     r2, [r6, #12]
        ldr     r7, [sp, #16]
        str     r7, [r6, #16]
        ldr     r7, [r1]
        str     r7, [r6, #20]
        ldr     r7, [r1, #4]
        str     r7, [r6, #24]
        ldr     r7, [r0, #8]
        str     r7, [r6, #28]
        ldr     r7, [sp, #20]
        str     r7, [r6, #32]
        ldr     r7, [sp, #24]
        str     r7, [r6, #36]
        ldr     r7, [sp, #28]
        str     r7, [r6, #40]
        ldr     r7, [sp, #32]
        str     r7, [r6, #44]
        ldr     r7, [sp, #36]
        str     r7, [r6, #48]
        ldr     r7, [sp, #40]
        str     r7, [r6, #52]
        ldr     r7, [sp, #44]
        str     r7, [r6, #56]
        ldr     r7, [sp, #48]
        str     r7, [r6, #60]
        tst     r5, #0x80
        bne     out
        cpsie   i
out:
        ldr     r12, [r4, #8]           @ original send function
        pop     {r4-r7, lr}
        bx      r12
        .balign 4
usec_reg:
        .word   0xc0242014
        .balign 256
hdr:                            @ 0x100
        .word   0x324f4953              @ 'SIO2'
        .word   0                       @ +4  index
        .word   0                       @ +8  original fn
        .word   0x50                    @ +12 channel mask
        .word   0                       @ +16 nent - 1
        .word   0                       @ +20 over_en
        .word   0                       @ +24 over_hits
        .space  0x24
        .balign 64
cmos:                           @ 0x140, 16 words
        .space  0x40
