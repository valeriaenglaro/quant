#!/usr/bin/env bash
# =====================================================================
#  QuantSuite one-click launcher (Linux / WSL Ubuntu)
#  - builds the ngn/k binary from k_source if ./k is missing
#    (k_source itself is NEVER modified: the build runs in a temp copy)
#  - checks the Python deps (numpy / scipy)
#  - starts the dual-engine server and opens the terminal in the browser
# =====================================================================
set -e
cd "$(dirname "$0")"

# ---- 1 · ngn/k binary -------------------------------------------------
if [ ! -x ./k ]; then
  SRC="${K_SOURCE:-$HOME/QuantSuite/k_source}"
  if [ ! -f "$SRC/makefile" ]; then
    echo "ngn/k source not found at: $SRC"
    echo "Set K_SOURCE=/path/to/k_source and re-run, or copy a prebuilt 'k' next to this script."
    exit 1
  fi
  echo "Building ngn/k from $SRC (in a temporary copy — k_source stays untouched)..."
  T="$(mktemp -d)"
  cp -r "$SRC"/. "$T"/
  ( cd "$T" && make k )
  cp "$T/k" ./k && chmod +x ./k && rm -rf "$T"
  echo "ngn/k built -> ./k"
fi

# ---- 2 · Python deps --------------------------------------------------
python3 -c 'import numpy, scipy' 2>/dev/null || {
  echo "Installing numpy/scipy..."
  pip3 install --user numpy scipy || pip3 install --user --break-system-packages numpy scipy
}

# ---- 3 · server + browser ---------------------------------------------
# app.py starts the server (python engine always; ngn/k engine because ./k exists)
# and opens http://localhost:8002/ in the default browser.
# On WSL: install 'wslu' (sudo apt install wslu) so the WINDOWS browser opens,
# or just open http://localhost:8002/ manually once the banner appears.
exec python3 app.py
