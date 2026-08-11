# QuantSuite — Linux server build (ngn/k native + Python)

> **Update (2026-08):** `master.k` now reproduces the Python baseline across the
> full battery — **58/58 cases to float round-off** (was 0/63). See
> [`PARITY_FIXES.md`](PARITY_FIXES.md) for the eight fixes, `ci_parity.py` for the
> gate, [`.github/workflows/ci.yml`](.github/workflows/ci.yml) for macOS+Linux CI
> that builds Amber and enforces parity, and [`GITHUB_PAGES.md`](GITHUB_PAGES.md)
> for publishing pre-computed output to GitHub Pages. Python was not modified.

The terminal (`index.html`, kept under the old name `QS.html` too) is served by
`server.py` and prices on **two server-side engines**: the native **ngn/k**
binary running `master.k`, and the Python reference `engine.py` (NumPy/SciPy).
The in-browser Pyodide/WASM engines were removed — every number comes from the
server.

## Files

| file            | status     | role |
|-----------------|-----------|------|
| `index.html`    | UPDATED    | the terminal (interactive charts, vanilla defaults; = `QS.html`) |
| `QS.html`       | UPDATED    | same file as `index.html` (kept under the old name) |
| `master.k`      | UPDATED    | ngn/k pricer — full risk metrics + in-kernel CRN greeks |
| `json.json`     | UPDATED    | vanilla sample ticket (1Y quarterly Phoenix, solve coupon) |
| `server.py`     | UPDATED    | dual-engine backend — robust k discovery, `/health` explains failures |
| `engine.py`     | one fix    | Python engine — autocall-schedule crash fix for non-1Y tenors (see below) |
| `app.py`        | unchanged  | desktop launcher (server + browser) |
| `k`             | BUILT      | ngn/k binary compiled from your `k_source` (unmodified) |
| `parity_tests.py`| NEW       | the big parity battery (battery + randomized structures) |
| `parity_report.md/json` | NEW| the proof: every compared number of the last full run |
| `verify.py`     | kept       | the earlier, smaller parity harness |
| `QuantSuite.sh` | launcher   | one-click (Linux / WSL) |
| `QuantSuite.bat`| launcher   | one-click (Windows → WSL) |

## "ngn/k not connecting" — fixed

`server.py` now searches for the `k` binary next to `server.py`, in the current
directory, `~/QuantSuite/app/k`, `~/k/k` and `$PATH`, **repairs a lost
executable bit automatically** (the usual culprit after the file transits a
Windows filesystem — that is almost certainly what happened on your machine),
refuses politely on Windows Python (the binary is a Linux ELF — run inside
WSL), and reports the exact reason in `GET /health` (`k_error` field) and in
the startup banner. If `/health` says `"k": true`, the engine is live.

Quick check inside WSL:

```bash
cd ~/QuantSuite/app
chmod +x k              # harmless if already executable
python3 server.py       # banner must say  ngn/k=True
curl localhost:8002/health
```

## ngn/k greeks

Greeks for `engine=k` are now computed **inside master.k** (CRN finite
differences, `greeks` flag 2 = basket, 3 = + per-asset) in a single k process —
no more thread-pool of bump subprocesses. `/full?engine=k&d=1` returns basket
greeks, `d=2` per-asset. Verified against `engine.py`'s finite differences on
identical draws (see the parity report; agreement ~1e-13).

## master.k risk block (complete set)

`p_autocall, expected_life_y, p_knock_in, p_capital_loss, exp_term_worst,
term_p05/p50/p95, var95_pct, var99_pct, es95_pct, es99_pct, p_loss, p_gain,
max_loss_pct, exp_return_pct` + terminal distribution (`dist`) + per-date
autocall counts (`acdist`). The extended metrics are cross-checked against the
same quantities computed from `engine.py`'s per-path P&L.

## Engine fixes in this round

1. **Autocall schedule crash (BOTH engines + the notebooks):**
   `obs_i = round(i/freq · days)` overshoots the simulation grid for every
   tenor ≠ 1Y (e.g. day 820 on an 18M/548-column grid → Python IndexError,
   k index error). Fixed symmetrically to evenly spaced observations with the
   last at maturity: `obs_i = round(i/total_obs · days)`. For 1Y tenors the
   dates are numerically identical to before. This is the single change made
   to `engine.py`; the notebooks (unchanged) still contain the old formula.
2. master.k: extended risk metrics, in-kernel greeks honoured by the server,
   `acdist`, plus all round-1 fixes (bround `2!f`, greeks flag, no dead BGK
   shift, q re-derivation on spot bumps, One-Star exclusion in `_risk`,
   `F0` leverage parse).

## Interactive charts

Payoff diagram and the risk-page Monte-Carlo chart use a built-in dependency-
free chart engine (QSIChart): **mouse-wheel zoom** (about the cursor,
shift = y-only), **drag to pan**, **double-click to reset**, a **draggable
legend box**, **click a legend label** to show/hide a series and **click the
colour swatch** to recolour any line (colours persist for the session). The
histogram strip on the risk chart is the *real* engine terminal distribution
and follows the zoom window. No CDN needed — works fully offline.

## Vanilla defaults

The ticket now opens on a standard product: single underlying (MSFT US), 1Y,
autocall 100% quarterly from Q1, conditional-with-memory coupon 70% quarterly,
European (maturity) KI 60%, put strike 100% (auto leverage), solve for the
coupon. `json.json` matches.

## One-click run (Linux / WSL Ubuntu)

```bash
mkdir -p ~/QuantSuite/app && cd ~/QuantSuite/app
# put here: index.html server.py engine.py app.py master.k json.json k QuantSuite.sh
chmod +x QuantSuite.sh k
./QuantSuite.sh
```

From Windows double-click `QuantSuite.bat` (edit `APPDIR` inside if needed).
Manual: `python3 server.py` → open http://localhost:8002/.

Single-file executable:

```bash
pip3 install pyinstaller
pyinstaller --onefile --name QuantSuite \
  --add-data "index.html:." --add-data "engine.py:." \
  --add-data "master.k:." --add-data "json.json:." --add-data "k:." app.py
```

## Testing (the proof)

```bash
python3 parity_tests.py                # battery (13 named) + 50 random structures
python3 parity_tests.py --random 200   # more
```

Identical numpy seed-42 normals are injected into master.k via `_Z`, so both
engines price the very same paths; agreement is float round-off (~1e-13), not
Monte-Carlo luck. Structural barrier solves are step functions — when the two
root-finders stop on opposite sides of a single path the case is re-checked
with the solved value pinned into both engines and must then match exactly
("step-edge" note in the report). Results: `parity_report.md` / `.json`.
