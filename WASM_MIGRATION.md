# QuantSuite → 100% client-side WebAssembly

QuantSuite now prices **entirely in the browser**. The Amber (ngn/k) interpreter
is compiled to WebAssembly and runs `master.k` locally — no backend server, no
`fetch` to an API, no CORS, no Render cold start, and it works offline once
loaded.

## How it works

```
 index.html ──loads──▶ amber-wasm.js ──fetch──▶ amber.wasm  (Amber interpreter, 262 KB)
      │                     │          ──fetch──▶ master.k   (the pricer)
      │                     ▼
      │           WebAssembly.instantiate(...)   env.{js_alloc,js_out,sin,cos,log,exp,…}
      │                     │
   srvFull(cfg) ───────────▶ AmberWASM.runAmberPricing(cfg)
                              1. JSON.stringify(cfg) → escaped, chunked K string literals
                              2. write "QSIN:…;" + master.k body into the wasm input buffer
                              3. qs_run() evaluates it; master reads its ticket from QSIN
                                 instead of json.json, prints the result JSON via js_out
                              4. parse → {PV,Solved,legs,risk,dist,greeks,acdist}
```

`master.k` is unmodified on disk; the loader swaps its one file-read
(`` `j?1:"json.json" ``) for the injected `QSIN` global at load time. Output is
**byte-identical to the native binary** (verified in Node against `amber_bin`).

## Files

| file | role |
|------|------|
| `amber.wasm` | Amber compiled to wasm32 (built by `build_wasm.sh`) |
| `wasm/qs_wasm.c` | custom wasm entry: `qs_init` / `qs_inbuf` / `qs_run` (no modules, no qSQL rewrite) |
| `build_wasm.sh` | reproducible build: clone Amber → clang `--target=wasm32` → `amber.wasm` |
| `amber-wasm.js` | browser loader: instantiate, JS heap allocator, math imports, `runAmberPricing(cfg)` |
| `app.js` | `QuantSuite.price(params)` / `priceWithUI(params,ui)` — same API, now WASM-backed |
| `index.html` | terminal; `srvFull`/`srvPrice`/`srvHealth` now call WASM (same JSON shape) |
| `wasm_smoke.js` | CI smoke test (prices the sample ticket, asserts shape) |
| `.github/workflows/ci.yml` | build wasm → smoke test → deploy static site to Pages |

## Rebuild the wasm locally

```bash
sudo apt-get install -y clang lld      # wasm-ld comes with lld
./build_wasm.sh                        # -> ./amber.wasm
python3 -m http.server 8099            # then open http://localhost:8099/index.html
```

## Deploy

Enable Pages once: **Settings → Pages → Source: GitHub Actions**. Then:

```bash
git checkout main

git add index.html app.js amber-wasm.js amber.wasm master.k \
        wasm/qs_wasm.c build_wasm.sh wasm_smoke.js \
        .github/workflows/ci.yml WASM_MIGRATION.md

git commit -m "Migrate QuantSuite to 100% client-side Amber WASM (no backend)"

git push origin main
```

The `Deploy QuantSuite (WASM) to GitHub Pages` workflow builds `amber.wasm`,
smoke-tests it, and publishes to `https://valeriaenglaro.github.io/QuantSuite/`.
Verify live:

1. Open the Pages URL; the header status shows the engine loaded.
2. Change Coupon / KI / paths / underlyings and price — the PV & coupon cards,
   risk tables (autocall prob, knock-in prob, expected life, VaR) and the payoff
   diagram update locally (status reads *"Priced in N ms via Amber WASM"*).
3. DevTools → Network shows **no** requests to any `/api/price` or Render domain
   after the initial static asset load.

## Honest notes

- **Performance.** In-browser pricing removes all network latency (previously a
  30–60 s Render cold start), but the Monte-Carlo compute is the same K code:
  ~80 ms at 500 paths, ~110 ms at 1 000, ~330 ms at 2 000, ~1.8 s at 10 000
  (risk block; +basket greeks adds ~40 %). The default is **2 000 paths**. The
  literal "<50 ms" only holds for very small path counts / price-only mode; the
  real win is zero latency and offline capability, not a fixed 50 ms.
- **Charts.** The terminal already ships a dependency-free chart engine
  (QSIChart) — no Chart.js/CDN is used or needed, so the payoff and risk-page
  charts keep working offline; they simply consume the WASM output now.
- **Margin page.** Margin analytics are pure Python (`engine.py`) and are **not**
  available in the offline WASM build; that panel reports a clear message. All
  pricing / risk / payoff features run fully in WASM.
- **Backend files** (`server.py`, `Dockerfile`, `render.yaml`, `requirements.txt`)
  remain in the repo as an optional server but are no longer used by the site.
