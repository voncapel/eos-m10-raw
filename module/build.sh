#!/bin/sh
# Build m10cine.flt against a CHDK trunk checkout.
#   module/build.sh [CHDK_DIR]      default CHDK_DIR = ./chdk (repo root)
# Tested with CHDK git ad402e1b (trunk 6307) and arm-none-eabi-gcc 16.2.
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
make -C "$T/modules" PLATFORM=m10 PLATFORMSUB=110d \
    CC="arm-none-eabi-gcc -std=gnu11 -Wno-incompatible-pointer-types -mlong-calls -fno-optimize-sibling-calls"
arm-none-eabi-size "$T/modules/.o4/m10_cine.o"
echo "-> $T/modules/.o4/m10cine.flt"
