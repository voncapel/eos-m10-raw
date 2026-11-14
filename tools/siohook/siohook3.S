@ siohook3.S - RAM hook for *(0x9b50): logging + CMOS override + TG override.
@ Position-independent Thumb-2 blob (m10sio.py).
@
@ CMOS (channel 6, single 16-bit frame reg<<12|val): per-register table at +0x140.
@ TG (channel 4, TgDrvWAKA addr-then-data pair): one override slot.  TG writes
@ come as two SIO frames from distinct return addresses: addr send returns to
@ tg_addr_lr (0xfc231323), data send to tg_data_lr (0xfc23132d).  When an addr
@ frame's value == tg_reg, a pending flag is set; the next data frame's value is
@ replaced by tg_val.  CDS/DFE/ppp channel-4 writes use other return addresses
@ and never set/consume pending.  All rewrites patch the caller's buffer only;
@ Canon's RAM shadows are untouched, so clearing the table reverts instantly.
@
@   0x000 poke32    0x010 hook    0x200 header    0x240 cmos[16]    0x280 ring
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
        cbz     r6, log
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
@ ---- TG override (channel 4, addr/data pair) ----
tg_ov:
        ldr     r6, [r4, #28]           @ tg_en
        cbz     r6, log
        ldr     r7, [sp, #16]           @ caller return address
        ldr     r6, [r4, #48]           @ tg_addr_lr
        cmp     r7, r6
        bne     2f
        @ addr frame: set pending = (value == tg_reg)
        ldr     r6, [r1]
        uxth    r6, r6
        ldr     r5, [r4, #32]           @ tg_reg
        uxth    r5, r5
        cmp     r6, r5
        ite     eq
        moveq   r6, #1
        movne   r6, #0
        str     r6, [r4, #44]           @ tg_pending
        b       log
2:
        ldr     r6, [r4, #52]           @ tg_data_lr
        cmp     r7, r6
        bne     log
        ldr     r6, [r4, #44]           @ tg_pending
        cbz     r6, log
        mrs     r3, apsr
        cpsid   i
        ldr     r5, [r4, #36]           @ tg_val
        ldr     r6, [r1]
        bfi     r6, r5, #0, #16
        str     r6, [r1]
        movs    r6, #0
        str     r6, [r4, #44]           @ clear pending
        ldr     r5, [r4, #40]
        adds    r5, #1
        str     r5, [r4, #40]           @ tg_hits
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
        add     r6, #0x80               @ ring = hdr + 0x80 = 0x280
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
        .word   0x334f4953              @ 'SIO3'
        .word   0                       @ +4  idx
        .word   0                       @ +8  orig fn
        .word   0x50                    @ +12 channel mask
        .word   0                       @ +16 nent - 1
        .word   0                       @ +20 cmos_en
        .word   0                       @ +24 cmos_hits
        .word   0                       @ +28 tg_en
        .word   0                       @ +32 tg_reg (target, low 16)
        .word   0                       @ +36 tg_val
        .word   0                       @ +40 tg_hits
        .word   0                       @ +44 tg_pending
        .word   0xfc231323              @ +48 tg_addr_lr
        .word   0xfc23132d              @ +52 tg_data_lr
        .space  0x8                     @ -> 0x240
cmos:                           @ 0x240
        .space  0x40
