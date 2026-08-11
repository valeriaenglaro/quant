# QuantSuite API — native Amber (ngn/k) engine + Flask, for Render.com
# Lightweight, fail-safe single-stage build on Ubuntu 22.04.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Toolchain + Python. Use build-essential (NOT bare gcc): it hard-depends on
# libc6-dev, so the C standard headers (string.h, stdio.h, math.h, stdint.h) are
# present. Bare `gcc` only *recommends* libc6-dev, which --no-install-recommends
# skips — that is what caused the "string.h: No such file or directory" failure.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git python3 python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Build the Amber (K) interpreter straight from the C sources ------------- #
# NOTE: the Amber sources use GNU C extensions (statement-expressions `({...})`,
# named variadic macros) and PTHREAD_MUTEX_RECURSIVE, so a strict `-std=c99`
# build fails. `-std=gnu11` compiles them cleanly; `-w` silences the (expected)
# warnings, `-fsigned-char` matches upstream build.sh. amber_wasm.c is guarded
# by `#if defined(wasm)` and compiles to nothing in a native build.
RUN git clone --depth 1 https://github.com/BonucciAndrea/amber.git /app/amber \
    && gcc -O3 -std=gnu11 -fsigned-char -w /app/amber/src/*.c -lm -lpthread -o /app/amber_bin \
    && printf '`0:$+/!100\n' > /tmp/smoke.k \
    && test "$(/app/amber_bin /tmp/smoke.k)" = "4950"

# --- Python deps (own layer so app-code changes don't re-run pip) ------------ #
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

# --- QuantSuite application code --------------------------------------------- #
COPY . /app/

ENV AMBER_BIN=/app/amber_bin \
    KSCRIPT=/app/master.k \
    PORT=8002

# Sanity: the native engine can price the sample ticket at build time.
RUN /app/amber_bin master.k >/dev/null

EXPOSE 8002

# Render injects $PORT at runtime; bind to it (default 8002 for local runs).
CMD ["sh", "-c", "gunicorn server:app --bind 0.0.0.0:${PORT:-8002} --workers 2 --threads 4 --timeout 120"]
