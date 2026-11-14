@ siohook.S - RAM hook for the M10 SioDrv send pointer *(0x9b50).
@ Position-independent Thumb-2 blob, injected over USB (m10sio.py).
@
@ Layout (offsets from blob base, all little-endian words):
@   0x000  poke32(addr, val): atomic 32-bit store, returns old value
@   0x010  hook entry  (r0 = hw struct, r1 = data ptr, r2 = nbits)
@   0x100  header: magic 'SIOH', idx, orig fn, chan mask, nent-1, ...
@   0x140  entries, 64 bytes each:
@          t_us, chan, cfg(hw[1]), nbits, lr, d0, d1, ctl(hw[2]), stack[8]
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
        ldr     r6, [r4, #12]           @ channel mask
        lsr     r6, r6, r5
        lsls    r6, r6, #31
        beq     out
        mrs     r5, apsr
        cpsid   i
        ldr     r6, [r4, #4]
        adds    r7, r6, #1
        str     r7, [r4, #4]
        msr     apsr_nzcvq, r5          @ flags only; restore I below
        ldr     r7, [r4, #16]           @ nent - 1
        ands    r6, r6, r7
        add     r6, r4, r6, lsl #6
        adds    r6, #0x40
        ldr     r7, usec_reg
        ldr     r7, [r7]
        str     r7, [r6, #0]
        ldr     r7, [r0]
        str     r7, [r6, #4]
        ldr     r7, [r0, #4]
        str     r7, [r6, #8]
        str     r2, [r6, #12]
        ldr     r7, [sp, #16]           @ return address
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
        @ restore the interrupt mask only after the entry is filled
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
        .word   0x484f4953              @ 'SIOH'
        .word   0                       @ +4  free-running index
        .word   0                       @ +8  original fn (set by host)
        .word   0x50                    @ +12 channel mask (ch4 | ch6)
        .word   0                       @ +16 nent - 1 (set by host)
        .space  0x2c
