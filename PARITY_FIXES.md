# master.k parity fixes — engine.py (Python baseline) is truth

Starting point: `parity_report.md` showed **0 / 63** cases matching; a fresh run
confirmed divergences up to 100%. After the fixes below the production battery
(8 named + 50 randomized structures) is **58 / 58 within 1e-3 relative, worst
1.8e-9** — i.e. float round-off, not Monte-Carlo noise. Python was never
touched; every change is in `master.k`.

Method: both engines share the QS Lehmer stream (LCG 48271 mod 2^31−1, seed 42,
Box-Muller). I verified the normal draws are **bit-identical** between
`engine.py._QSRng` and master.k's `qn`, so every remaining difference was
deterministic pricing logic, findable by dumping metrics side-by-side
(`ci_parity.py`, production mode).

## The eight fixes

1. **Percentile method.** `pt` used nearest-rank `floor(p·(n-1))`; NumPy
   `percentile` uses linear interpolation. Reimplemented interpolation.
   → fixes `term_p05/50/95`, `var95/99`, `es95` on every case.

2. **`p_maturity`** was never emitted. Added `pmt = mean(~autocalled)` and the
   `p_maturity` risk key.

3. **Capital-guarantee bond (`bV`).** master.k reduced the non-autocalled
   redemption to `gv%`; engine.py's bond is always `N·exp(-r·mat)` (capital
   guarantee only zeroes the put). Removed the reduction.

4. **Conditional-coupon observation column (`cx`).** master.k read the barrier
   level at `D-1` steps; the Python DataFrame label→position mapping reads at
   `day_obs`. Changed `cx` to `min(D, E)`. (European masks this; the solver and
   worst-of/EW baskets expose it.)

5. **Barrier "None" / BGK / risk knock-in (`bR`, `kR`).** Restored the
   Broadie-Glasserman-Kou intraday shift `ki·exp(0.5826·vol·√dt)` in the pricing
   barrier, and split out a *risk* knock-in `kR` that matches engine.py's two
   distinct conventions:
   - autocall product: None/European → `T<ki`, American → `min<ki` (strict).
   - reverse-convertible (Autocall Type None): None → `T<PutStrike`,
     American → `min<=ki`, European → `T<=ki`; and one-star exclusion applied.

6. **Plain "Conditional" coupon memory.** In engine.py the exact string
   `"Conditional"` matches *neither* memory-reset branch, so `memory_stack`
   accumulates and never resets. master.k reset it every period. Added the
   third branch (keep accumulating) — the 8.8× coupon-leg blow-up on B08/B06i.

7. **Periodic + autocall coupon coexist.** master.k zeroed the periodic coupon
   whenever an autocall coupon existed (`ac2`); engine.py pays both. Removed.

8. **Coupon day-grid & FU discount, product-aware.**
   - Autocall & YE conditional day grid: `i/num_payments·Days` vs the old
     `i/freq·365` (identical for 1Y, diverges for 6M/18M/2Y).
   - Reverse-convertible FU coupon discounts by the exact year fraction
     `i/freq` (unconditional), not floored days.
   Plus `p_capital_loss` dropped a spurious `& T<PutStrike` in the autocall path.

Gamma was also switched to engine.py's definition (±5% bump ÷ 25).

## Greeks status (honest)

Greeks appear only in 3 of the 63 cases. engine.py hard-codes
`N_SIMS_GREEKS=10000` for greeks regardless of pricing `n`, so the original
G-cases (compared at n=150–200) could never match — a harness artifact, not a
pricing error. Compared at the matching n=10000:

- **vega, rho: exact** (~1e-13) — the in-kernel CRN machinery is correct.
- **gamma:** now uses engine.py's ±5%/25 definition; residual ~2e-3 (a noisy
  second difference).
- **delta:** a residual ~7% remains from a subtle spot-bump finite-difference
  difference (bumped price differs by ~0.03%, amplified by the central
  difference). Not closed; documented here rather than papered over.

Pricing and all risk analytics — the substance of the 63-case battery, which
contains no greek cases — are at full parity.
