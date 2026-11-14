/* Host simulation of the EXACT device header, never opens USB or card files.
 * cc -std=c11 -Wall -Wextra -Werror test_m10tasktrace_device.c -o /tmp/m10ts-test
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
static unsigned now_us, tick, arm_calls, arm_result, mode, callback_pending;
static int (*good_fn)(int,int);
static unsigned char signature[20];
static const unsigned char expected_sig[20] = {
    0x08,0x48,0x00,0x68,0x10,0xb1,0x4f,0xf0,0xff,0x30,
    0x70,0x47,0x04,0x48,0x00,0x68,0x00,0x6c,0x70,0x47};
static unsigned table_base, table_count, current_ptr;
static unsigned char tcbs[2 * 0x54];
static unsigned char names_tcm[32], names_rom[32];
static unsigned forbidden_name_reads;
static unsigned literal_current;
static void put32(unsigned char *p, unsigned v) { memcpy(p, &v, 4); }
static unsigned fake32(unsigned a) {
    unsigned v;
    assert((a >> 24) != 0xc0 && (a >> 24) != 0xd0);
    if (a == 0x8040) return mode == 3 ? 0 : 1;
    if (a == 0x803c) return current_ptr;
    if (a == 0x80c0) return table_base;
    if (a == 0x80f4) return table_count;
    if (a == 0xbfe10f70) return literal_current;
    if (a == 0xbfe10f74) return 0x8040;
    if (a >= 0x680124 && a + 4 <= 0x680124 + sizeof(tcbs)) {
        memcpy(&v, tcbs + a - 0x680124, 4); return v;
    }
    assert(!"unexpected RAM word read"); return 0;
}
static unsigned char fake8(unsigned a) {
    if ((a >> 24) == 0xc0 || (a >> 24) == 0xd0) {
        forbidden_name_reads++; assert(!"MMIO name dereference");
    }
    if (a >= 0xbfe10f50 && a < 0xbfe10f50 + sizeof(signature)) return signature[a - 0xbfe10f50];
    if (a >= 0x680124 && a < 0x680124 + sizeof(tcbs)) return tcbs[a - 0x680124];
    if (a >= 0xbfe115d4 && a < 0xbfe115d4 + 32) return names_tcm[a - 0xbfe115d4];
    if (a >= 0xfc123000 && a < 0xfc123000 + 32) return names_rom[a - 0xfc123000];
    assert(!"unexpected RAM byte read"); return 0;
}
#define TS_READ32(a) fake32(a)
#define TS_READ8(a) fake8(a)
static unsigned usec(void) { return now_us & 0xfffff; }
static unsigned udiff(unsigned a,unsigned b) { return (b-a)&0xfffff; }
static unsigned get_tick_count(void) { return tick; }
static int SetHPTimerAfterNow(unsigned period, int(*good)(int,int), int(*bad)(int,int), int param) {
    assert(period >= 1000 && period <= 10000); good_fn=good; arm_calls++;
    if (arm_result == 0x15) bad(0,param);
    callback_pending = !(arm_result & 1);
    return (int)arm_result;
}
static void msleep(unsigned t) {
    tick += t ? 10 : 0; now_us += 1000;
    if (callback_pending && mode != 2) { callback_pending=0; good_fn(0,0); }
}
static void slog(const char *s,unsigned a,unsigned b) { (void)s;(void)a;(void)b; }
static unsigned char task_file[64 + 65536 * 8], name_file[16 + 256 * 44];
static unsigned task_file_n, name_file_n;
static int fake_open(const char *path, int flags, int permission) {
    (void)flags; (void)permission;
    if (!strcmp(path,"A/M10TSK.BIN")) { task_file_n=0; return 10; }
    assert(!strcmp(path,"A/M10TSN.BIN")); name_file_n=0; return 11;
}
static int fake_write(int fd, const void *data, unsigned count) {
    unsigned *n = fd == 10 ? &task_file_n : &name_file_n;
    unsigned cap = fd == 10 ? sizeof(task_file) : sizeof(name_file);
    unsigned char *dst = fd == 10 ? task_file : name_file;
    assert(fd == 10 || fd == 11); assert(*n + count <= cap);
    memcpy(dst + *n, data, count); *n += count; return (int)count;
}
static int fake_close(int fd) { assert(fd == 10 || fd == 11); return 0; }
#define open fake_open
#define write fake_write
#define close fake_close
#include "../module/m10_tasktrace.h"
#undef open
#undef write
#undef close
static ts_record records[TS_CAP];
static unsigned char extra[TS_EXTRA];
static unsigned file_word(const unsigned char *file,unsigned word) {
    unsigned v; memcpy(&v,file + word * 4,4); return v;
}
static void reset(void) {
    ts_buf=records; ts_period=1000; ts_n=ts_pending=ts_busy=ts_pinned=0;
    ts_on=1; ts_prev_u=ts_start_u=0; ts_elapsed=ts_bad=ts_arm_error=ts_full=ts_max_us=0;
    ts_start_tick=tick=now_us=arm_calls=arm_result=mode=callback_pending=0;
    ts_anchor=TS_NO_ANCHOR; ts_nonirq=forbidden_name_reads=0;
    memcpy(signature,expected_sig,sizeof(signature)); literal_current=0x803c;
    table_base=current_ptr=0x680124; table_count=2;
    memset(tcbs,0,sizeof(tcbs));
    put32(tcbs + 0x40,0x10001); put32(tcbs + 0x24,0xbfe115d4);
    put32(tcbs + 0x0c,0xbfe10801);
    put32(tcbs + 0x54 + 0x40,0x10002); put32(tcbs + 0x54 + 0x24,0xfc123000);
    put32(tcbs + 0x54 + 0x0c,0xfc120001);
    memset(names_tcm,0,32); memcpy(names_tcm,"idle",4);
    memset(names_rom,'a',32);
}
int main(void) {
    _Static_assert(sizeof(ts_record)==8,"TSK ABI");
    _Static_assert(sizeof(ts_name)==44,"TNM ABI");
    reset(); assert(ts_kernel_ok());
    signature[0]^=1; assert(!ts_kernel_ok()); signature[0]^=1;
    literal_current=0x8038; assert(!ts_kernel_ok()); literal_current=0x803c;
    table_count=1025; assert(!ts_kernel_ok()); table_count=2;
    table_base=0xc0000000; assert(!ts_kernel_ok()); table_base=0x680124;
    current_ptr++; assert(!ts_kernel_ok()); current_ptr--;
    put32(tcbs + 0x40,0x10002); assert(!ts_kernel_ok()); put32(tcbs + 0x40,0x10001);
    tcbs[0x49]=0xff; assert(!ts_kernel_ok()); tcbs[0x49]=0;
    ts_names=(ts_name *)extra; ts_snapshot_names(); assert(ts_name_n==2);
    assert(!strcmp(ts_names[0].name,"idle")); assert(strlen(ts_names[1].name)==31);
    put32(tcbs + 0x54 + 0x24,0xc0242014); ts_snapshot_names();
    assert(ts_name_n==2 && ts_names[1].name[0]==0 && forbidden_name_reads==0);
    reset(); ts_start(extra); assert(ts_pending && arm_calls==1);
    now_us=1000; callback_pending=0; good_fn(0,0);
    assert(ts_n==1 && ts_buf[0].elapsed==1000 && ts_buf[0].task==0x680124 && ts_pending);
    ts_first_readout(1200); assert(ts_stop() && !ts_pending && !ts_busy && !ts_pinned);
    ts_save(); assert(task_file_n==64+8 && name_file_n==16+2*44);
    assert(file_word(task_file,0)==0x314b5354 && file_word(task_file,3)==1);
    assert(file_word(task_file,15)==1200);
    assert(((file_word(task_file,7)+file_word(task_file,9))&0xfffff)==file_word(task_file,8));
    assert(file_word(name_file,0)==0x314d4e54 && file_word(name_file,2)==44);
    reset(); ts_period=0; ts_start(extra); assert(!ts_pending && !ts_on && !arm_calls);
    tick=5000; now_us=5000000; assert(ts_stop()); ts_save();
    assert(task_file_n==64 && file_word(task_file,3)==0 && file_word(task_file,15)==TS_NO_ANCHOR);
    reset(); arm_result=5; ts_arm(); assert(!ts_pending && !ts_on && ts_arm_error==5 && !ts_bad);
    reset(); arm_result=0x17; ts_arm(); assert(!ts_pending && !ts_on && ts_arm_error==0x17 && !ts_bad);
    reset(); arm_result=0x15; ts_arm(); assert(!ts_pending && !ts_on && ts_bad==1 && arm_calls==1);
    reset(); ts_prev_u=0xffff0; ts_elapsed=0; now_us=0x100020; ts_good(0,0);
    assert(records[0].elapsed==48);
    reset(); ts_n=TS_CAP-1; now_us=1000; ts_good(0,0);
    assert(ts_n==TS_CAP && ts_full && !ts_on && !ts_pending && arm_calls==0);
    now_us=5000000; assert(ts_stop() && ts_stop_elapsed==1000 && ts_stop_u==1000);
    reset(); mode=3; now_us=1000; ts_good(0,0); assert(ts_n==0 && ts_pinned && !ts_on && ts_nonirq==1 && !ts_stop());
    reset(); mode=3; ts_on=0; ts_pending=1; ts_good(0,0); assert(ts_pinned && !ts_pending && !ts_stop());
    reset(); mode=2; ts_arm(); assert(!ts_stop() && ts_pinned && ts_pending);
    reset(); ts_start_u=0xffff0; tick=10; ts_first_readout(0x20); assert(ts_anchor==48);
    reset(); tick=1100; ts_first_readout(0x20); assert(ts_anchor==TS_NO_ANCHOR);
    puts("PASS: exact device header preflight, RAM/TCM names, no-MMIO guards, TSK/TNM export, OFF/ON, drain, failures, wrap, full, non-IRQ, pin, anchor");
    return 0;
}
