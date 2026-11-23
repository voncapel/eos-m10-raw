#!/usr/bin/env python3
"""Host regression of the actual v172 C kick/duplicate-worker branch (no USB)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[1]
SOURCE = (_ROOT / 'module/m10_cine.c' if (_ROOT / 'module/m10_cine.c').exists()
          else _ROOT / 'src/chdk/trunk/modules/m10_cine.c')


def body_at(text, marker):
    start = text.index(marker)
    first = text.index('{', start)
    depth = 1
    end = first + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[first:end]


class HEFixTest(unittest.TestCase):
    def test_failed_restore_preserves_error_frame_identity(self):
        text = SOURCE.read_text()
        marker = '// an early kick proves' if '// an early kick proves' in text else '// v172b: an early kick proves'
        start = text.index(marker)
        end = text.index('            if (lj_on && x_ready > fr', start)
        code = text[start:end].replace('*(volatile unsigned *)(0x0000fa68 + 0x1c)', 'head_error')
        program = '''#include <assert.h>
unsigned lj_on=1,x_he_fix=1,head_error=0x40,lj_kicked=8,lj_cnt=7,fr=7;
int classify(int r) {\n''' + code + '''\nreturn r; }
int main(void) {
 assert(classify(-1)==1 && fr==7);
 assert(classify(2)==1 && fr==7);
 lj_kicked=0;assert(classify(-1)==-1);
 lj_cnt=8;assert(classify(-1)==1 && fr==7);
 head_error=0;assert(classify(-1)==-1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            src, exe = Path(d) / 'restore.c', Path(d) / 'restore'
            src.write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=3)

    def test_late_error_is_not_published(self):
        collect = body_at(SOURCE.read_text(), 'static int lj_collect(void)')
        program = r'''
#include <assert.h>
#define LJ_DUP_N 16
#define LJ_N 64
unsigned lj_kicked=5,cb_done=1,cb_us,lj_dup_t,lj_dup_h=1;
unsigned lj_dup_q[16]={4},lj_sz[64],lj_us[64],lj_err,lj_cnt=4,published;
int xr_sem,lj_sem;
void tlf_set(unsigned a,unsigned b,unsigned c) {(void)a;(void)b;(void)c;}
unsigned enc_end(unsigned *us) {*us=100;return 16;}
void GiveSemaphore(int s) {(void)s;}
void lj_vidf(unsigned k,unsigned sz) {(void)k;(void)sz;published++;}
''' + '\nint lj_collect(void)\n' + collect + r'''
int main(void) {
 assert(lj_collect()==1);
 assert(!lj_kicked && lj_cnt==4 && !published);
 lj_dup_h=0;lj_kicked=5;
 assert(lj_collect()==1 && lj_cnt==5 && published==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            src, exe = Path(d) / 'collect.c', Path(d) / 'collect'
            src.write_text(program)
            subprocess.run(['cc', '-std=c11', '-O2', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=3)

    def test_actual_kick_and_worker(self):
        text = SOURCE.read_text()
        kick = body_at(text, 'static void lj_kick(unsigned fr)\n')
        task = body_at(text, 'static void lj_task(void)\n')
        worker = body_at(task, 'if (x_kick)')
        # Replace outer-loop continue/break only with returning to the host scheduler.
        # Inner-loop continue/break must retain their firmware meaning.
        worker = worker.rsplit('TakeSemaphore(lj_sem, 20);', 1)[0] + 'return; }'
        worker = worker.replace('if (xr_stop && !lj_kicked && lj_dup_t >= lj_dup_h) break;',
                                'if (xr_stop && !lj_kicked && lj_dup_t >= lj_dup_h) return;')
        worker = worker.replace('if (lj_err || xr_err) break;\n            TakeSemaphore',
                                'if (lj_err || xr_err) return;\n            TakeSemaphore')
        # The error/stop statements at branch end now live outside the firmware for-loop.
        worker = worker.replace('if (lj_err || xr_err) break;\n            ',
                                'if (lj_err || xr_err) return;\n            ')
        prelude = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#define XR_MAX 64
#define LJ_N 64
#define LJ_DUP_N 16
unsigned lj_cnt, lj_kicked, cb_done, xr_stop, xr_err, lj_err;
unsigned lj_kwait=8000, lj_ns=1, x_ready, xr_wr, lj_cslot_n=3;
unsigned lj_raw_n=3, xr_fb=128, lj_eoff, lj_cbase, lj_cslot_sz=1024;
unsigned x_he_fix=1;
#define LJ_MAP_N 16
volatile unsigned lj_map[LJ_MAP_N];
unsigned lj_dup_q[LJ_DUP_N], lj_dup_h, lj_dup_t;
unsigned lj_prev_tot=512, lj_prev_sz=16, x_dup_us_max;
unsigned xr_slot[XR_MAX], xr_tick[XR_MAX], xr_wus[XR_MAX], lj_sz[LJ_N], lj_us[LJ_N];
unsigned lj_k_no[4], lj_k_ok, lj_k_max, lj_phys, enc_u0;
unsigned enc_in_off, enc_out_off, enc_out_size, fake_us, sleeps, collects, begins;
int xr_sem, lj_sem, x_kick=1;
unsigned char storage[4096], *lj_buf=storage;
unsigned usec(void) { return fake_us+=100; }
unsigned udiff(unsigned a,unsigned b) { return b-a; }
void msleep(unsigned t) { fake_us+=10000; assert(++sleeps<20 && "worker spin / deadlock"); }
void GiveSemaphore(int s) { (void)s; }
void TakeSemaphore(int s,unsigned t) { (void)s;(void)t; }
int lj_collect(void) { ++collects; return lj_kicked ? 0:1; }
int enc_begin(char *b,unsigned p,unsigned f) { (void)b;(void)p;(void)f; ++begins;return 1; }
void tlf_set(unsigned k,unsigned f,unsigned t) { (void)k;(void)f;(void)t; }
void put32(unsigned char *p,unsigned v) { memcpy(p,&v,4); }
'''
        main = r'''
static void reset(void) {
 lj_cnt=3;lj_kicked=0;xr_wr=3;xr_stop=xr_err=lj_err=0;
 lj_dup_h=1;lj_dup_t=0;lj_dup_q[0]=4;x_ready=5;
 begins=collects=sleeps=fake_us=0;
 for(unsigned j=0;j<LJ_MAP_N;j++) lj_map[j]=j%lj_cslot_n;
}
int main(void) {
 reset();
 lj_kick(0);
 assert(begins==1 && lj_kicked==4 && "pending duplicate must allow older frame encode");
 reset();lj_cnt=4;lj_dup_q[0]=4;
 lj_kick(0);
 assert(!begins && !sleeps && "duplicate at head must not start JpCore or sleep");
 reset();lj_kicked=3;cb_done=1;
 worker();
 assert(collects==0 && "only capture task may collect encoder");
 reset();lj_cnt=4;lj_dup_q[0]=4;
 memset(storage+0*1024,0x5a,512);xr_tick[4]=123;
 worker();
 assert(lj_cnt==5 && lj_dup_t==1 && xr_wus[4]==512);
 assert(lj_slot(4)==lj_slot(3));
 assert(storage[32]==0x5a && storage[1024+32]==0); // worker must not copy or mutate shared header
 // Writer may lag; next encoder must not overwrite any pending/shared payload.
 lj_dup_h=lj_dup_t=0;x_ready=6;xr_wr=3;
 lj_kick(0);assert(lj_kicked==6 && lj_slot(5)!=lj_slot(4));
 // Repeated duplicates share one physical slot across logical ring wrap.
 reset();lj_cnt=4;lj_dup_q[0]=4;lj_dup_q[1]=5;lj_dup_h=2;
 worker();assert(lj_cnt==6 && lj_dup_t==2 && lj_slot(5)==lj_slot(4));
 assert(lj_free_slot()!=lj_slot(5));
 // Exhaustively enumerate valid logical maps for small rings and backlogs.
 for(unsigned n=2;n<=5;n++) for(unsigned count=1;count<20;count++) {
  lj_cslot_n=n;lj_cnt=count;xr_wr=count;
  for(unsigned j=0;j<LJ_MAP_N;j++)lj_map[j]=j%n;
  unsigned free=lj_free_slot();assert(free<n && free!=lj_slot(count-1));
  for(unsigned backlog=1;backlog<n;backlog++) {
   xr_wr=count>backlog?count-backlog:0;
   free=lj_free_slot();assert(free<n);
   for(unsigned j=xr_wr;j<lj_cnt;j++)assert(free!=lj_slot(j));
  }
 }
 lj_cslot_n=3;
 reset();lj_cnt=4;xr_wr=1;xr_stop=1;
 worker();
 assert(lj_dup_t==0 && "stop must not bypass occupied compressed slot");
 puts("actual C HEFIX kick/worker checks passed");
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'hefix.c'
            exe = Path(d) / 'hefix'
            mapping = text[text.index('static unsigned lj_slot(unsigned k)'):text.index('static void lj_vidf(unsigned k, unsigned sz)')]
            src.write_text(prelude + mapping + '\nstatic void lj_kick(unsigned fr)\n' + kick +
                           '\nstatic void worker(void)\n' + worker + '\n' + main)
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=3)


if __name__ == '__main__':
    unittest.main()
