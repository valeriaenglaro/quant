# Margin & Collateral — cross-engine (Python + Amber/WASM) update

This change set makes the **Margin & Collateral** tab run natively on **both**
engines with a bit-for-bit-identical JSON contract, and removes the previous
"Python-only" restriction so margin works fully offline in the browser via the
Amber (`master.k`) WebAssembly build.

## What changed

### 1. `master.k` — native margin analytics (Amber)
- Added a **theta** greek (1-day time-decay) via a maturity-parameterised reprice
  (`Em`, `mkSch`, `thP`). Because the pricer uses common random numbers, the
  `Days-1` paths are the base paths truncated by one column, so theta is computed
  on the existing path matrix without re-simulating.
- Fixed the local-vol **skew anchor** under spot bumps (`b0:B%SP[i]` instead of
  `b0:B%S0`) so Amber's delta/gamma match `engine.py`, which anchors the skew to
  the fixing. Base price / vega / rho were already identical; this closes
  delta/gamma to ~1e-11.
- Added a full **Margin & Collateral** section (gated on a `margin` sub-dict in
  the ticket). It computes, in native `k`:
  - Initial Margin via Schedule %, Sensitivity (greeks × multipliers) and
    Monte-Carlo **VaR / Expected Shortfall** over the MPOR, with Euler
    attribution and a P&L histogram.
  - Maintenance & close-out margin (IM × multipliers).
  - Variation Margin from MTM and **collateral coverage %** via the
    LTV → per-issuer concentration cap → haircut waterfall.
  - Respects every UI parameter: Risk Vol (σ), MPOR days, Vol-of-Vol,
    Rate Vol (bp), Notional override, Quantile %, netting/ignore toggles.
  - Returns `initial_margin` (`im_pct`/`im_amount`), `maintenance_margin`,
    `closeout_margin`, `variation_margin`, `collateral_coverage` (`coverage_pct`)
    plus the full diagnostics the terminal renders.
- The Monte-Carlo uses the **same Lehmer LCG + Box–Muller** already shared with
  `engine.py`, and a shared Acklam inverse-normal for the z-quantile, so the two
  engines agree to floating-point noise.
- Implementation notes: the interpreter caps each lambda at 16 locals / 255
  constants and the global table at 256 slots, so the margin block accumulates
  every intermediate into a single top-level dict `S` and splits the output into
  a handful of sub-dict globals. Pricing is untouched when no `margin` key is
  present.

### 2. `engine.py` — aligned to the same contract
- Margin Monte-Carlo now draws from the shared `_QSRng` (Lehmer LCG) instead of
  NumPy's PCG64, and the z-quantile uses the shared Acklam approximation
  (`_mg_ppf`) instead of `scipy.norm.ppf`. Output dictionary shape is unchanged.

### 3. `index.html` / `amber-wasm.js` — frontend + WASM
- Removed the guard that threw *"Margin analytics require the Python engine"*.
- `srvPost('/margin', …)` now runs the Amber WASM engine (`master.k` returns the
  margin dict); full **offline** margin, no backend.
- "Compute margin" and the automatic recalculations run for **either** engine
  selection (Amber/Kona or Python); offline builds map both to Amber WASM.
- Margin booleans and collateral `exempt` are sent as `1/0` (the k JSON reader
  has no native boolean; `engine.py._mg_bool` accepts `1/0` too).

### 4. `server.py` — both engines for the hosted API
- Pricing strips any `margin` key before calling the pricer.
- `/margin` routes to native Amber (`master.k`) when Amber is selected, and to
  `engine.py.compute_margin` when Python is selected.

## Parity verified
- Greeks (delta/gamma/vega/rho/theta): ~1e-9–1e-11 across autocall, YE,
  American, high-skew, reoffer-solve and multi-asset basket tickets.
- Margin dictionary: **0 field differences** between `engine.py` and both the
  native `k` binary and the `amber.wasm` interpreter, across methods 1/2/3,
  VaR & ES, schedule floor, variation margin, netting toggles, empty/multi
  collateral, and single/basket products.
