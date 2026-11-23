# Omar on DIGIC 6 (EOS M10 `1.10d` ROM Analysis)

During the `eos-m10-raw` project we did not need to patch or hijack **Omar** to achieve continuous 14-bit RAW video on the EOS M10 — and understanding *why* turned out to be an interesting data point about how Canon actually uses Omar on single-DIGIC 6 cameras compared to dual-DIGIC 6 bodies like the 7D Mark II.

All addresses, layouts, and behaviours below are extracted directly from the EOS M10 `1.10d` firmware (`0xfc000000` ROM base).

---

## 1. TL;DR — What Omar Is on EOS M10 (`1.10d`)

- **Hardware**: A second **ARMv7-R Cortex-R4** core inside DIGIC 6 (Thumb-2 ISA, `SCTLR.TE = 1` Thumb exception vectors) with its own **32 KiB ATCM** (`0x00000000`), **64 KiB BTCM** (`0x80000000`), and **100 KiB shared-DRAM image** (`0x00780000`).
- **OS**: Its own complete **DryOS v2.3 (release `#0057`)** kernel and interactive Dry-shell (`Dry[OMAR]>`), running alongside the main core (`Dry[MARIUS]>`).
- **Role on EOS M10**: **Sensor AutoFocus (SAF / Hybrid CMOS AF II) coprocessor only**, plus clock-gear coordination (`ClkgenGearApi` / `MLHClock_DUKE`) and inter-core mailbox IPC (`postman_me.c` ↔ `postman_mm.c`).
- **Critical contrast with 7D Mark II**: On the EOS M10, Omar's entire 100 KiB binary contains **zero references to EDMAC (`0xc0f0/c0f2/c0f3/c0f5`), PACK32, JpCore, or ImgSens**. All sensor/EDMAC/PACK32/JpCore registers are driven directly by **Marius**, which is why `m10cine.flt` can run continuous PACK32 → CH12 → JpCore RAW capture purely from Marius without fighting Omar over EDMAC ownership.

---

## 2. Architecture & Memory Map

Omar's own Dry-shell `memmap` routine (ROM `0xfc61500c`, executed at Omar VA `0x0078bed8`) prints its exact TCM and stack layout:

| Region | Omar Virtual Address | Marius Bus Alias | Size | Notes |
|---|---:|---:|---:|---|
| **Exception vectors** | `0x00000000` | `0xdff00000` | — | Reset = ARM `ldr pc, [pc, #24]` → `0x00000d98`; all other vectors = Thumb-2 `ldr.w pc, [pc, #28]` (`SCTLR.TE = 1`) |
| **ATCM** | `0x00000000 – 0x00008000` | `0xdff00000 – 0xdff08000` | 32 KiB | Initialised from ROM `0xfc6082ac` (`0x0e88` B); `DRY_ERREX_STACK` at `0x00003c00 – 0x00004000` (1 KiB) |
| **BTCM** | `0x80000000 – 0x80010000` | — | 64 KiB | `DRY_EXCEP_STACK` at `0x80000000 – 0x80000800` (2 KiB) |
| **Shared DRAM image** | `0x00780000 – 0x007986b0` | `0x40780000` (uncached) | `0x186b0` B (~97.7 KiB) | Initialised from ROM `0xfc609134`; runtime BSS/state sits around `0x00797xxx` (e.g. `0x00797744` `OmarStop`, `0x00797784` `ClkgenGearApi`) |

Notice the constant ROM-to-RAM offset for Omar's main DRAM section:
```
ROM_addr - Omar_VA = 0xfc609134 - 0x00780000 = 0xfbe89134
```
Branches from DRAM into ATCM (`0x0000xxxx`) cross-check cleanly against this exact delta (for example, `KerInt` at ROM `0xfc6100dc` / VA `0x00786fa8` branches directly to ATCM `0x00000788`).

---

## 3. Boot, Reset & Shutdown Sequence (Marius → Omar)

Marius boots and stops Omar through two small routines near `postman_mm.c`, controlled by a hardware block at **`0xd20f0000`**:

### Scatter-load descriptor table (ROM `0xfc6217e4`)

| Segment | Destination (Marius addr) | Source (ROM addr) | Size (bytes) | Target on Omar |
|---|---:|---:|---:|---|
| 0 | `0xdff00000` | `0xfc6082ac` | `0x00000e88` (3,720 B) | ATCM (`0x00000000`) |
| 1 | `0x40780000` | `0xfc609134` | `0x000186b0` (100,016 B) | DRAM (`0x00780000`, uncached write) |

### Boot sequence (Marius `0xfc1ed67c`)

1. Checks Marius RAM flag `*(0x000084dc) == 1`; returns immediately if Omar is already running.
2. Writes **`0`** to **`0xd20f0110`** — holds Omar in reset.
3. Writes **`2`** to **`0xd20f0110`** — enables bus access to Omar's ATCM window (`0xdff00000`) while keeping the core halted.
4. Copies the 24-byte table from `0xfc6217e4` to the stack and invokes DMA/scatter-copy helper `0xfc127f78(0, table, 2)` to populate both ATCM and DRAM.
5. Writes **`3`** to **`0xd20f0110`** — releases Omar from reset; Omar boots from `0x00000000` → `0x00000d98`.
6. Sets `*(0x000084dc) = 1`.

### Graceful shutdown sequence (Marius `0xfc1ed6b6`, called from `0xfc44354c`)

1. Sends a **Postman channel 4** message `(1, 0, 0)` via `0xfc1eccba(4, 1, 0, 0)`.
2. On Omar, the `OmarStop` task (ROM `0xfc60e9e2`, VA `0x007858ae`, registered at `0xfc60e9f6`) wakes on its semaphore, disables interrupts (`0xfc60ffca`), and executes **`wfi`**.
3. Marius delays `50 ms` (using hardware µs timer `0xc0210000 + 0xc`) and polls **`0xd20f0118 == 1`** (Omar `STANDBYWFI` status) up to `10 × 20 ms` (`200 ms`).
4. If Omar fails to assert WFI in time, Marius logs `"force2reset\n"` (`0xfc1ed738`).
5. Marius writes `0` (bits `[1:0] = 0`) to **`0xd20f0110`** to place Omar back into reset and clears `*(0x000084dc) = 0`. *(Quirk in `1.10d` at `0xfc1ed700`: Marius actually stores the literal `0xd20f0110` into `[0xd20f0000 + 0x110]`, which has low bits `00`.)*

---

## 4. Inter-Core Mailbox (`0xd2000000`: `postman_mm.c` ↔ `postman_me.c`)

Marius and Omar communicate over a dedicated hardware FIFO mailbox at **`0xd2000000`**:

- **Marius driver**: `postman_mm.c` (ROM `0xfc1ecd9c`, MMIO accesses at `0xfc1eca52`, `0xfc1eca9c`, `0xfc1ecb3e`, `0xfc1ecd12`).
- **Omar driver**: `postman_me.c` (ROM `0xfc60ee38`, MMIO accesses at `0xfc60ea5a`, `0xfc60eaf6`, `0xfc60eb9e`, `0xfc60ed66`, `0xfc60eec2`).
- **Channel layout**: 6 channels (`0..5`), stride **`0x40` bytes** (`base = 0xd2000000 + ch * 0x40`):
  - `+0x00`: FIFO status / pending count
  - `+0x04`: 2-word (64-bit) message FIFO port (each message pushes/pops two consecutive 32-bit words)
  - `+0x0c`: channel IRQ acknowledge (write `0`)
  - Control/routing registers at `0xd2000410` and `0xd2000424`
- **Direction split**: Bitmask `0x2a` (`0b101010`) partitions odd vs even channels into RX and TX queues (with a 9-entry software ring buffer per TX channel in `postman_me.c`).
- **Known channels**:
  - **Channel 4**: core lifecycle (`OmarStop` shutdown command from Marius `0xfc1ed6c8`).
  - **SAF IPC**: `SAFMOComMariusOMARAPI.c` (ROM `0xfc5e6f98`) ↔ `SAFMOComOmarOMARAPI.c` (ROM `0xfc615324`) ("Marius-Omar Com" for Sensor AutoFocus), brought up by `SAFState.c` (`InitializeSAF > SAF_OMAR_MODE` at `0xfc54a0f0`).

---

## 5. Peripherals & Subsystems Owned by Omar on EOS M10

Every `.c` module compiled into Omar's `1.10d` image (`0xfc609134 – 0xfc6217e4`):

| Subsystem | Source Files / Tasks in Omar Image | Purpose |
|---|---|---|
| **DryOS Kernel & Shell** | `Intc.c`, `KerInt.c`, `KerSem.c`, `KerFlag.c`, `KerQueue.c`, `KerRLock.c`, `KerTask.c`, `KerMisc.c`, `Memory.c`, `Dry[OMAR]>` | Full DryOS microkernel + Dry-shell (`task`, `sem`, `event`, `mq`, `mutex`, `memmap`, `meminfo`, `dminfo`, `mkcfg`, `stdlibcfg`, `xd`, `xm`, `suspend`, `resume`) |
| **IPC & Lifecycle** | `postman_me.c`, `OmarStop` | Mailbox driver (`0xd2000000`) and WFI shutdown task |
| **Clock / Power Gear** | `MLHClock_DUKE.c`, `ClkgenGearApi.c` (`ClockSave`) | Shared DUKE clock-gen block (`0xd2090000`) |
| **Sensor AutoFocus (SAF)** | `SAFMOComOmarOMARAPI.c`, `SAFTaskAPI.c`, `SAFPredictAction.c`, `SAFSafariAction.c`, `pppTblMngOmar.c` (`PppTblOmarTask`), `HivCalcOmarTask`, `SAFKizuDataOmar.c` / `SAFKizuMemoryMgr.c` (`SAFKizuOmartTask`) | Phase-difference correlation (`HivCalc`), AF prediction/tracking, sensor defect/AF-pixel masking (`Kizu`), and parameter table management |

### Hardware blocks touched by Omar (`1.10d`)

- **Interrupt Controller (`0xd4010008`, `0xd4012000`)**: Same DIGIC 6 INTC architecture as Marius (`0xfc1fb288` / `0xfc1fb294`), with **432 (`0x1b0`) IRQ vectors** (`Intc.c` / `KerInt.c` at `0xfc610008`).
- **System Timer (`0xc0210000`)**: Standard µs/1 ms timer (`Timer1m`, `UTimer`).
- **DUKE Clock-Gen & Per-Core Clock Gear (`0xd2090000`, `0xd209f150`, `0xd209f158`)**:
  - This is the **one hardware block where Marius and Omar directly share adjacent registers** — and it connects directly to our `v186` JpCore `3.35×` speedup:
    - `0xd209f150`: shared clock-gear control (Omar sets bit 4 `0x10` at `0xfc61001e`).
    - **`0xd209f154`**: **Marius** clock-gear register (managed by Marius `ClkgenGearApi.c` at `0xfc1ec6c2`, with refcounted `ClockSave` hold/release at `0xfc1ec6d7` / `0xfc1ec6ed`).
    - **`0xd209f158`**: **Omar** clock-gear register (managed by Omar `ClkgenGearApi.c` at `0xfc61002c`: writes `6` when Omar's `ClockSave` refcount hits `0`, restores `[0x00797784]` when active).
  - Holding Marius's `ClockSave` (`0xfc1ec6d7`) together with `LCLK_HOLD0` (`0xfc1803f3`) boosts JpCore from `100 MB/s` to **`339 MB/s`** on Marius without needing any Omar-side changes.
- **Not touched by Omar on EOS M10**: `0` references to `0xc0f0xxxx` (TG/Head/ImgSens), `0xc0f2xxxx` / `0xc0f3xxxx` (PACK32 / EDMAC / JpCore), or `0xc0f5xxxx` (CH24 YUV EDMAC).

---

## 6. Implications for RAW Video & Open Ideas for DIGIC 6 Research

1. **Why continuous AF still had to be off**: Even though Omar does not touch EDMAC directly on the M10, Canon's Marius-side `SAFRawPath` (`0xc0f08510`, `0xc0f37240`) feeds sensor AF data to Omar (`SAF_OMAR_MODE`) when Continuous AF / Movie Servo AF is enabled. Keeping AF in MF or One-Shot leaves the sensor readout and bus completely quiet during RAW recording.
2. **Why M10 behaves differently from 7D Mark II**: On dual-DIGIC 6 cameras (e.g. 7D2), Canon splits imaging/EDMAC duties across cores differently. On single-DIGIC 6 mirrorless bodies like the M10 (and likely M3 / G7X / G3X — worth cross-checking their ROMs), Omar appears to be strictly an AF/SAF offload core while Marius retains full control of the imaging pipeline.
3. **Untapped potential — Omar as a free 2nd Cortex-R4 coprocessor**: Because Marius has complete control over Omar's reset (`0xd20f0110`), ATCM bus window (`0xdff00000`), DRAM image (`0x40780000`), WFI status (`0xd20f0118`), and hardware mailbox (`0xd2000000`), a future DIGIC 6 hack (CHDK or Magic Lantern) could cleanly halt SAF (`0xfc1ed6b6`) during manual-focus RAW video and load custom ARMv7-R code onto Omar — giving an **entire idle Cortex-R4 with 96 KiB of TCM** for real-time debayering, focus peaking, scopes, or lossless encoding without stealing a single cycle from Marius.
