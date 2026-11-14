#!/bin/bash
# usage: decomp.sh out.c addr...
cd "$(dirname "$0")/.." && P=$(pwd)
export JAVA_HOME=/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home
out="$P/$1"; shift
/opt/homebrew/Cellar/ghidra/*/libexec/support/analyzeHeadless "$P/ghidra" M10 -process -noanalysis -scriptPath "$P/scripts" -postScript Decomp.java "$out" "$@" > "$P/ghidra/decomp.log" 2>&1
echo "exit=$?"
