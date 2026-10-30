#!/bin/sh
# SP-K1: build the compiled _stamp_move kernel. Source and this script are
# committed; the produced .dylib is gitignored (rebuilt on demand).
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
clang -O3 -ffp-contract=off -fno-fast-math -shared -o "$DIR/libstamp.dylib" "$DIR/stamp.c"
echo "built $DIR/libstamp.dylib"
