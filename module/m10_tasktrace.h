/* v153: bounded read-only DryOS task sampler, M10 110d runtime-gated.
 * Included after usec()/udiff()/slog(). No task-name dereference in callbacks.
 * Timer good callbacks may also be dispatched synchronously by Canon: sample
 * outside IRQ we stop and pin the allocation/module (no epilogue/unload race).
 * Stop drains the one-shot chain; on timeout memory and module stay pinned.
 */
#ifndef M10_TASKTRACE_H
#define M10_TASKTRACE_H
#ifndef TS_READ32
#define TS_READ32(a) (*(volatile unsigned *)(a))
#define TS_READ8(a) (*(volatile unsigned char *)(a))
#endif
#define TS_CAP 65536u
#define TS_NAME_CAP 256u
#define TS_NAME_BYTES (TS_NAME_CAP * 44u)
#define TS_EXTRA (TS_CAP * 8u + TS_NAME_BYTES)
#define TS_CURRENT 0x803cu
#define TS_NO_ANCHOR 0xffffffffu

typedef struct { unsigned elapsed, task; } ts_record;
typedef struct { unsigned ptr, id, entry; char name[32]; } ts_name;
static ts_record *ts_buf;
static ts_name *ts_names;
static unsigned ts_period, ts_name_n, ts_start_u, ts_stop_u, ts_stop_elapsed;
static unsigned ts_prev_u, ts_elapsed, ts_bad, ts_arm_error, ts_max_us, ts_full;
static unsigned ts_nonirq, ts_anchor = TS_NO_ANCHOR, ts_start_tick;
static volatile unsigned ts_on, ts_pending, ts_busy, ts_n, ts_pinned;

static int ts_kernel_ok(void)
{
    /* 110f kernel signature; 110d veneer targets the same RAM address.
     * MUST match actual 110d RAM, never assume that the kernels are identical. */
    static const unsigned char sig[20] = {0x08,0x48,0x00,0x68,0x10,0xb1,0x4f,0xf0,0xff,0x30,0x70,0x47,0x04,0x48,0x00,0x68,0x00,0x6c,0x70,0x47};
    unsigned i, base, count, cur;
    for (i = 0; i < sizeof(sig); i++) if (TS_READ8(0xbfe10f50u + i) != sig[i]) return 0;
    if (TS_READ32(0xbfe10f70) != TS_CURRENT || TS_READ32(0xbfe10f74) != 0x8040) return 0;
    base = TS_READ32(0x80c0); count = TS_READ32(0x80f4); cur = TS_READ32(TS_CURRENT);
    if (!count || count > 1024 || (base & 3) || base < 0x8000 || base > 0x20000000u - count * 0x54) return 0;
    if (cur < base || cur >= base + count * 0x54 || (cur - base) % 0x54) return 0;
    return (TS_READ32(cur + 0x40) & 0xffff) == (cur - base) / 0x54 + 1 && TS_READ8(cur + 0x49) != 0xff;
}

static void ts_snapshot_names(void)
{
    unsigned base, count, i;
    ts_name_n = 0;
    if (!ts_kernel_ok()) return;
    base = TS_READ32(0x80c0); count = TS_READ32(0x80f4);
    for (i = 0; i < count && ts_name_n < TS_NAME_CAP; i++) {
        unsigned p = base + i * 0x54, id = TS_READ32(p + 0x40), name, j;
        ts_name *r;
        if (TS_READ8(p + 0x49) == 0xff || (id & 0xffff) != i + 1) continue;
        name = TS_READ32(p + 0x24);
        r = ts_names + ts_name_n++;
        r->ptr = p; r->id = id; r->entry = TS_READ32(p + 0x0c);
        memset(r->name, 0, sizeof(r->name));
        if (!((name >= 0x8000 && name <= 0x20000000u - 32) || (name >= 0xbfe10800u && name <= 0xbfe1741du - 32) || (name >= 0xfc000000u && name <= 0xffffffe0u))) continue;
        for (j = 0; j < 31; j++) { char c = TS_READ8(name + j); r->name[j] = c; if (!c) break; }
    }
}

static int ts_good(int deadline, int param);
static int ts_bad_cb(int deadline, int param)
{
    (void)deadline; (void)param;
    /* Called synchronously on deadline failure. Never rearm recursively. */
    ts_bad++; ts_on = 0; ts_pending = 0;
    return 0;
}

static void ts_arm(void)
{
    int h;
    ts_pending = 1;  /* before Set: its failure callback may run synchronously */
    h = SetHPTimerAfterNow(ts_period, ts_good, ts_bad_cb, 0);
    if (h & 1) { ts_arm_error = (unsigned)h; ts_on = 0; ts_pending = 0; }
}

static int ts_good(int deadline, int param)
{
    unsigned u, n, cost, task;
    (void)deadline; (void)param;
    ts_busy = 1;
    /* Canon can dispatch queued good callbacks from another task. It could be
     * preempted inside our return epilogue: pin BEFORE clearing pending, even
     * when stop was already requested. Only IRQ returns permit normal unload. */
    if (!TS_READ32(0x8040)) { ts_pinned = 1; ts_nonirq++; ts_on = 0; ts_pending = 0; ts_busy = 0; return 0; }
    ts_pending = 0;
    if (!ts_on) { ts_busy = 0; return 0; }
    u = usec();
    ts_elapsed += udiff(ts_prev_u, u); ts_prev_u = u;
    n = ts_n;
    task = TS_READ32(0x8040) ? TS_READ32(TS_CURRENT) : 0;
    if (!task) ts_nonirq++;
    ts_buf[n].elapsed = ts_elapsed; ts_buf[n].task = task;
    ts_n = n + 1;
    cost = udiff(u, usec());
    if (cost > ts_max_us) ts_max_us = cost;
    if (ts_n == TS_CAP) { ts_full = 1; ts_on = 0; }
    else ts_arm();
    ts_busy = 0;
    return 0;
}

static void ts_start(void *extra)
{
    ts_names = (ts_name *)extra;
    ts_buf = (ts_record *)((char *)extra + TS_NAME_BYTES);
    ts_n = ts_pending = ts_busy = ts_on = ts_pinned = 0;
    ts_elapsed = ts_bad = ts_arm_error = ts_max_us = ts_full = ts_nonirq = 0;
    ts_anchor = TS_NO_ANCHOR;
    ts_snapshot_names();
    ts_start_tick = get_tick_count();
    ts_start_u = ts_prev_u = usec();
    ts_stop_u = ts_start_u; ts_stop_elapsed = 0;
    if (ts_period) { ts_on = 1; ts_arm(); }
}

static void ts_first_readout(unsigned u)
{
    /* The timer and timeline use the same 20-bit clock. Only accept an anchor
     * inside its first turn; don't silently invent an epoch after a long wait. */
    if (ts_period && get_tick_count() - ts_start_tick < 1000)
        ts_anchor = udiff(ts_start_u, u & 0xfffff);
}

static int ts_stop(void)
{
    unsigned t = get_tick_count();
    ts_on = 0;
    while ((ts_pending || ts_busy) && get_tick_count() - t < 100) msleep(1);
    if (ts_pending || ts_busy) ts_pinned = 1;
    if (ts_pinned) return 0;
    /* Full/error stops can precede this task by seconds: don't derive elapsed
     * from a last sample then, since that could lose whole 20-bit turns. */
    if (ts_period && ts_n && !ts_full && !ts_arm_error && !ts_bad) {
        ts_stop_u = usec(); ts_stop_elapsed = ts_elapsed + udiff(ts_prev_u, ts_stop_u);
    } else if (ts_n) {
        ts_stop_elapsed = ts_buf[ts_n - 1].elapsed;
        ts_stop_u = (ts_start_u + ts_stop_elapsed) & 0xfffff;
    }
    if (ts_anchor != TS_NO_ANCHOR && ts_anchor > ts_stop_elapsed) ts_anchor = TS_NO_ANCHOR;
    return 1;
}

static void ts_save(void)
{
    unsigned hd[16] = {0x314b5354,64,8,ts_n,TS_CAP,ts_period,TS_CURRENT,
        ts_start_u,ts_stop_u,ts_stop_elapsed,ts_bad,ts_arm_error,ts_max_us,ts_full,153,ts_anchor};
    int fd = open("A/M10TSK.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) { write(fd, hd, sizeof(hd)); if (ts_n) write(fd, ts_buf, ts_n * sizeof(ts_record)); close(fd); }
    fd = open("A/M10TSN.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) { unsigned nh[4] = {0x314d4e54,ts_name_n,sizeof(ts_name),153}; write(fd, nh, sizeof(nh)); if (ts_name_n) write(fd, ts_names, ts_name_n * sizeof(ts_name)); close(fd); }
    slog("v153 task period=%d samples=%d", ts_period, ts_n);
    slog("  v153 task bad=%d arm_error=%d", ts_bad, ts_arm_error);
    slog("  v153 task store_us_max=%d full=%d", ts_max_us, ts_full);
    slog("  v153 task nonirq=%d pinned=%d", ts_nonirq, ts_pinned);
}
#endif
