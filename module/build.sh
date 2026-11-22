#!/bin/sh
# Build m10cine.flt against a CHDK trunk checkout.
#   module/build.sh [CHDK_DIR]      default CHDK_DIR = ./chdk (repo root)
# Tested with CHDK git ad402e1b (trunk 6307) and arm-none-eabi-gcc 16.2.
#
# -mword-relocations is required: PV_HOT (pv_render_m1*) is compiled at -O2, which otherwise emits
# MOVW/MOVT pairs (R_ARM_MOVW_ABS_NC / R_ARM_MOVT_ABS) that the CHDK .flt loader cannot relocate.
# The build fails unless m10_cine.o and m10cine.elf carry R_ARM_ABS32 relocations only, and on any
# compiler warning in m10_cine.c.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
CHDK=${1:-$HERE/../chdk}
T="$CHDK/trunk"
[ -f "$T/modules/Makefile" ] || { echo "no CHDK trunk at $T"; exit 1; }
cp "$HERE/m10_cine.c" "$HERE/m10_tasktrace.h" "$HERE/m10_blobs.h" "$T/modules/"
cp "$HERE/localbuildconf.inc" "$T/"
if ! grep -q m10cine "$T/modules/Makefile"; then
    (cd "$CHDK" && git apply "$HERE/chdk-modules-Makefile.patch")
fi
make -C "$T/tools" PLATFORM=m10 PLATFORMSUB=110d >/dev/null
LOG="$T/modules/.o4/m10_build.log"   # inside the build tree (always writable when make is)
mkdir -p "$T/modules/.o4"
set +e
make -C "$T/modules" PLATFORM=m10 PLATFORMSUB=110d \
    CC="arm-none-eabi-gcc -std=gnu11 -Wno-incompatible-pointer-types -mlong-calls -fno-optimize-sibling-calls -mword-relocations" \
    >"$LOG" 2>&1
RC=$?
set -e
cat "$LOG"
[ "$RC" -eq 0 ] || { echo "FAIL: make exited $RC"; exit "$RC"; }
W=$(grep -c 'm10_cine\.c.*warning:' "$LOG" || true)
echo "m10_cine.c warnings: $W"
[ "$W" -eq 0 ] || { echo "FAIL: compiler warnings in m10_cine.c"; exit 1; }
for f in "$T/modules/.o4/m10_cine.o" "$T/modules/.o4/m10cine.elf"; do
    [ -f "$f" ] || { echo "FAIL: missing $f"; exit 1; }
    BAD=$(arm-none-eabi-readelf -rW "$f" | awk '/R_ARM_/ && $3 != "R_ARM_ABS32" {print $3}' | sort | uniq -c)
    N=$(arm-none-eabi-readelf -rW "$f" | grep -c 'R_ARM_ABS32' || true)
    if [ -n "$BAD" ]; then echo "FAIL: non-ABS32 relocations in $f:"; echo "$BAD"; exit 1; fi
    echo "ONLY_ABS32_OK $(basename "$f") ($N x R_ARM_ABS32)"
done
arm-none-eabi-size "$T/modules/.o4/m10_cine.o"
echo "-> $T/modules/.o4/m10cine.flt"
