@ siohook5.S - RAM hook for *(0x9b50): logging + CMOS table + TG/DFE table.
@ v5: the ch4 table also matches DfeAccs addr/data frames (LR +56/+60).
@ Position-independent Thumb-2 blob (m10sio.py).
@
@ Same as v3 but the TG override is a 16-entry table instead of one slot.
@ TG writes (TgDrvWAKA) come as two SIO frames: addr frame returns to
@ tg_addr_lr (0xfc231323), data frame to tg_data_lr (0xfc23132d).  On an addr
@ frame the table is searched (entry = reg<<16 | val, reg != 0); a match stores
@ pending = index+1.  The next data frame gets the entry's value.  Entries with
@ reg == 0 are unused.  tg_en gates everything.
@
@   0x000 poke32  0x010 hook  0x200 header  0x240 cmos[16]  0x280 tg[16]  0x2c0 tgmatch[16]  0x300 ring
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
        ldr     r5, [r0]                @ channel
        cmp     r5, #6
        beq     cmos_ov
        cmp     r5, #4
        beq     tg_ov
        b       log
@ ---- CMOS override (channel 6) ----
cmos_ov:
        ldr     r6, [r4, #20]           @ cmos_en
        cmp     r6, #0
        beq     log
        cmp     r2, #16
        bne     log
        mrs     r3, apsr
        cpsid   i
        ldr     r6, [r1]
        ubfx    r7, r6, #12, #4
        add     r5, r4, #0x40
        ldr     r5, [r5, r7, lsl #2]
        lsls    r12, r5, #15            @ bit16 enable -> N
        bpl     1f
        bfi     r6, r5, #0, #12
        str     r6, [r1]
        ldr     r5, [r4, #24]
        adds    r5, #1
        str     r5, [r4, #24]           @ cmos_hits
1:
        tst     r3, #0x80
        bne     log
        cpsie   i
        b       log
@ ---- TG table override (channel 4, addr/data pair) ----
tg_ov:
        ldr     r6, [r4, #28]           @ tg_en
        cmp     r6, #0
        beq     log
        ldr     r7, [sp, #16]           @ caller return address
        ldr     r6, [r4, #48]           @ tg_addr_lr
        cmp     r7, r6
        beq     8f
        ldr     r6, [r4, #56]           @ dfe_addr_lr
        cmp     r7, r6
        bne     3f
8:
        @ addr frame: search table, pending = idx+1 or 0
        ldr     r6, [r1]
        uxth    r6, r6
        cbz     r6, 5f                  @ reg 0 never matches
        add     r5, r4, #0x80           @ tg table
        movs    r3, #0
2:
        ldr     r7, [r5, r3, lsl #2]
        cmp     r6, r7, lsr #16
        beq     4f
        adds    r3, #1
        cmp     r3, #16
        blt     2b
5:
        movs    r3, #0
        str     r3, [r4, #44]
        b       log
4:
        adds    r3, #1
        str     r3, [r4, #44]           @ pending = idx+1
        b       log
3:
        ldr     r6, [r4, #52]           @ tg_data_lr
        cmp     r7, r6
        beq     9f
        ldr     r6, [r4, #60]           @ dfe_data_lr
        cmp     r7, r6
        bne     log
9:
        ldr     r6, [r4, #44]           @ tg_pending
        cmp     r6, #0
        beq     log
        mrs     r3, apsr
        cpsid   i
        subs    r6, #1
        add     r5, r4, #0xc0           @ match table
        ldr     r5, [r5, r6, lsl #2]
        lsls    r12, r5, #15            @ bit16 = match enabled -> N
        bpl     6f
        ldr     r7, [r1]
        eors    r7, r5
        lsls    r7, r7, #16             @ low 16 bits equal?
        beq     6f
        movs    r6, #0
        str     r6, [r4, #44]           @ mismatch: clear pending, no rewrite
        b       7f
6:
        add     r5, r4, #0x80
        ldr     r5, [r5, r6, lsl #2]    @ entry
        ldr     r6, [r1]
        bfi     r6, r5, #0, #16
        str     r6, [r1]
        movs    r6, #0
        str     r6, [r4, #44]           @ clear pending
        ldr     r5, [r4, #40]
        adds    r5, #1
        str     r5, [r4, #40]           @ tg_hits
7:
        tst     r3, #0x80
        bne     log
        cpsie   i
@ ---- logging ring ----
log:
        ldr     r5, [r0]
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
        ldr     r7, [r4, #16]
        ands    r6, r6, r7
        add     r6, r4, r6, lsl #6
        add     r6, #0x100              @ ring = hdr + 0x100 = 0x300
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
        ldr     r12, [r4, #8]
        pop     {r4-r7, lr}
        bx      r12
        .balign 4
usec_reg:
        .word   0xc0242014
        .balign 512
hdr:                            @ 0x200
        .word   0x354f4953              @ 'SIO5'
        .word   0                       @ +4  idx
        .word   0                       @ +8  orig fn
        .word   0x50                    @ +12 channel mask
        .word   0                       @ +16 nent - 1
        .word   0                       @ +20 cmos_en
        .word   0                       @ +24 cmos_hits
        .word   0                       @ +28 tg_en
        .word   0                       @ +32 (unused in v4)
        .word   0                       @ +36 (unused in v4)
        .word   0                       @ +40 tg_hits
        .word   0                       @ +44 tg_pending (idx+1)
        .word   0xfc231323              @ +48 tg_addr_lr
        .word   0xfc23132d              @ +52 tg_data_lr
        .word   0xfc1bd4e3              @ +56 dfe_addr_lr
        .word   0xfc1bd4ed              @ +60 dfe_data_lr
cmos:                           @ 0x240
        .space  0x40
tgtab:                          @ 0x280  reg<<16 | value
        .space  0x40
tgmatch:                        @ 0x2c0  bit16 | original value to require
        .space  0x40
