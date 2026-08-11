#!/usr/bin/env bash
# Build amber.wasm — the Amber (ngn/k) interpreter compiled to WebAssembly, for
# QuantSuite's 100% client-side (in-browser) pricing. Reproducible: clones the
# Amber engine, drops in our custom wasm entry point (wasm/qs_wasm.c), and links
# with clang/wasm-ld into a single freestanding module.
#
#   deps: clang (>=14) + lld (provides wasm-ld).  Ubuntu:  apt-get install clang lld
#   usage: ./build_wasm.sh            # produces ./amber.wasm
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
AMBER_DIR="${AMBER_DIR:-amber_src}"
AMBER_URL="${AMBER_URL:-https://github.com/BonucciAndrea/amber.git}"
[ -d "$AMBER_DIR" ] || git clone --depth 1 "$AMBER_URL" "$AMBER_DIR"
cp wasm/qs_wasm.c "$AMBER_DIR/src/qs_wasm.c"
mkdir -p "$AMBER_DIR/src/o/w" && : > "$AMBER_DIR/src/o/w/fs.h"   # empty embedded VFS (unused: input via QSIN global)
SRCS=$(ls "$AMBER_DIR"/src/*.c | grep -v amber_wasm.c)          # qs_wasm.c replaces amber_wasm.c
clang --target=wasm32 -Dwasm -O2 -ffreestanding -nostdlib -fno-builtin \
  -isystem "$AMBER_DIR/src/wsys" -I "$AMBER_DIR/src" \
  -Wl,--no-entry -Wl,--allow-undefined \
  -Wl,--export=qs_init -Wl,--export=qs_inbuf -Wl,--export=qs_run \
  -Wl,--export=memory -Wl,--export=__heap_base \
  $SRCS -o amber.wasm
echo "built amber.wasm ($(wc -c < amber.wasm) bytes)"
