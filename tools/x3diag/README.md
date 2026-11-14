# x3diag: decoders for LVX3S.BIN / LVX3.BIN

Small diagnostic scripts written during the Film 1×3 / 3×3 sessions (live83 to live86).
They read the files that `tools/m10x3raw.py` downloads into `captures/live71/`.
They are kept for reference; the current x5 magnifier work does not need them.

Usual prefix: `P = captures/live71/<tag>_`, then pass `P` or the file.

| script | input | what it shows |
|---|---|---|
| `prof.py P` | `P`+`LVX3S.BIN`, `P`+`LVX3.BIN` | one row per pass: `dt`, `st`, lines received, `tick`, plus the DMA profile (first/last line, longest gap) |
| `pm.py P`+`LVX3S.BIN` | `LVX3S.BIN` | DMA profile only, per trace slot (0-15) |
| `stg.py P`+`LVX3S.BIN` | `LVX3S.BIN` | the 12 `STG` stages of each pass (µs, `_tgTask`, ImgSens state): where the time goes |
| `snap.py P`+`LVX3S.BIN` | `LVX3S.BIN` | fine DMA timeline, SIO events (`8830`, CMOS bursts), and the last 60 SIO frames before a shutdown |
| `tl_view.py P`+`LVX3S.BIN` | `LVX3S.BIN` | DMA pointer trace next to Canon's EDMAC channels (`c0f04308`, `c0f04108`, `c0f26608`, `4608`) |
| `dfd.py P`+`LVX3S.BIN` | `LVX3S.BIN` | engine shadow diff during each DMA (v71) |
| `frsig.py` | `LVX3S.BIN` | signature of cut frames (v66/v84) |
| `emap.py`, `emap2.py` | `LVX3E.BIN` | EDMAC activity map (v63) |
| `d8830.py`, `ringfail.py`, `tgcommits.py` | `LVX3S.BIN` | narrow helpers: relative `8830` position, ring contents, TG commits |

Example:

```bash
python3 tools/x3diag/prof.py captures/live71/r86c_
python3 tools/x3diag/stg.py  captures/live71/r86c_LVX3S.BIN
```

`stg.py` and `snap.py` assume the v31+ layout of `LVX3S.BIN`: 8-word header,
160 × 40-byte `tl_rec`, SIO ring of `hd[4] × 64` bytes, then `stg` (16 × 12 × 4 words),
then `x_pm`, then `x_df`.
