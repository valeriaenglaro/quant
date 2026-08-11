# QuantSuite parity proof - engine.py (Python) vs master.k (ngn/k)

Run: 2026-08-10 11:28 - production mode, shared QS Lehmer stream (48271 mod 2^31-1,
seed 42, Box-Muller). Both engines draw identical paths, so residual
differences are float round-off, not Monte-Carlo noise.

**58 / 58 cases PASS** (relative tolerance 0.001)

| # | case | n | worst rel diff | result |
|---|------|---|----------------|--------|
| 1 | B01 vanilla Phoenix (json.json, solve coupon) | 10000 | 5.95e-13 | PASS |
| 2 | B02 4-name worst-of, solve KI barrier | 10000 | 1.02e-09 | PASS |
| 3 | B03 EW basket, memory coupon, dividends, price reoffer | 10000 | 8.85e-14 | PASS |
| 4 | B04 snowball, variable barrier, one-star, solve AC coupon | 10000 | 1.22e-13 | PASS |
| 5 | B05 capital-guaranteed 95, at-maturity coupon | 10000 | 6.22e-12 | PASS |
| 6 | B06 18M custom barrier schedule | 10000 | 3.71e-14 | PASS |
| 7 | B07 reverse convertible (no autocall), solve coupon | 10000 | 2.21e-12 | PASS |
| 8 | B08 2Y monthly autocall from M6 | 10000 | 5.36e-14 | PASS |
| 9 | R01 547d 4U Equally Weighted / cpn Fixed Unconditional/Monthly / AC None/Yearly+Snowball / | 1200 | 2.06e-14 | PASS |
| 10 | R02 182d 1U None / cpn Conditional with Memory/Monthly / AC Constant Barrier/SemiAnnually+ | 1200 | 1.61e-14 | PASS |
| 11 | R03 365d 2U Worst-Of / cpn None/Yearly / AC Constant Barrier/Quarterly+None / KI None 62.5 | 1200 | 1.54e-14 | PASS |
| 12 | R04 730d 3U Equally Weighted / cpn None/Monthly / AC None/Quarterly+Flat / KI None 59.4 /  | 1200 | 7.92e-15 | PASS |
| 13 | R05 547d 3U Worst-Of / cpn None/SemiAnnually / AC Constant Barrier/Monthly+None / KI Ameri | 1200 | 7.08e-15 | PASS |
| 14 | R06 365d 1U None / cpn Conditional with Memory/Quarterly / AC Variable Barrier/SemiAnnuall | 1200 | 1.54e-14 | PASS |
| 15 | R07 547d 2U Worst-Of / cpn Conditional/Quarterly / AC Constant Barrier/SemiAnnually+None / | 1200 | 3.87e-14 | PASS |
| 16 | R08 730d 2U Worst-Of / cpn Conditional with Memory/Quarterly / AC Issuer Callable/SemiAnnu | 1200 | 1.03e-14 | PASS |
| 17 | R09 182d 3U Equally Weighted / cpn None/Yearly / AC None/Quarterly+None / KI European (Mat | 1200 | 6.74e-15 | PASS |
| 18 | R10 730d 3U Worst-Of / cpn Fixed Unconditional/Monthly / AC Constant Barrier/SemiAnnually+ | 1200 | 4.07e-14 | PASS |
| 19 | R11 182d 1U None / cpn Conditional with Memory/SemiAnnually / AC Issuer Callable/SemiAnnua | 1200 | 1.04e-12 | PASS |
| 20 | R12 365d 1U None / cpn Conditional/SemiAnnually / AC Constant Barrier/Monthly+None / KI No | 1200 | 4.91e-15 | PASS |
| 21 | R13 547d 4U Equally Weighted / cpn Conditional/Monthly / AC Issuer Callable/SemiAnnually+N | 1200 | 1.81e-14 | PASS |
| 22 | R14 365d 1U None / cpn Conditional with Memory/Quarterly / AC Constant Barrier/Yearly+Flat | 1200 | 2.03e-14 | PASS |
| 23 | R15 365d 1U None / cpn Fixed Unconditional/Monthly / AC Constant Barrier/SemiAnnually+None | 1200 | 6.73e-14 | PASS |
| 24 | R16 365d 4U Equally Weighted / cpn Conditional with Memory/Quarterly / AC Constant Barrier | 1200 | 9.22e-15 | PASS |
| 25 | R17 730d 1U None / cpn Conditional/At Maturity / AC Issuer Callable/Monthly+None / KI Amer | 1200 | 2.75e-13 | PASS |
| 26 | R18 182d 2U Worst-Of / cpn Fixed Unconditional/At Maturity / AC Issuer Callable/SemiAnnual | 1200 | 1.25e-12 | PASS |
| 27 | R19 547d 1U None / cpn Conditional with Memory/Monthly / AC Variable Barrier/SemiAnnually+ | 1200 | 6.99e-14 | PASS |
| 28 | R20 365d 1U None / cpn Conditional with Memory/Yearly / AC Constant Barrier/Yearly+Snowbal | 1200 | 2.63e-14 | PASS |
| 29 | R21 730d 4U Worst-Of / cpn Conditional with Memory/Quarterly / AC Constant Barrier/Quarter | 1200 | 7.77e-15 | PASS |
| 30 | R22 730d 4U Worst-Of / cpn Fixed Unconditional/Quarterly / AC Variable Barrier/Quarterly+F | 1200 | 2.55e-14 | PASS |
| 31 | R23 365d 2U Worst-Of / cpn None/At Maturity / AC Constant Barrier/SemiAnnually+Flat / KI A | 1200 | 7.08e-15 | PASS |
| 32 | R24 182d 4U Worst-Of / cpn None/At Maturity / AC Constant Barrier/Quarterly+Snowball / KI  | 1200 | 3.18e-14 | PASS |
| 33 | R25 730d 4U Equally Weighted / cpn None/Quarterly / AC Issuer Callable/Yearly+Flat / KI Eu | 1200 | 2.22e-14 | PASS |
| 34 | R26 365d 1U None / cpn Conditional/Quarterly / AC Variable Barrier/Monthly+Flat / KI None  | 1200 | 1.23e-09 | PASS |
| 35 | R27 365d 3U Worst-Of / cpn None/Quarterly / AC Issuer Callable/Yearly+None / KI American D | 1200 | 2.29e-13 | PASS |
| 36 | R28 365d 3U Worst-Of / cpn Conditional with Memory/At Maturity / AC Constant Barrier/Quart | 1200 | 1.29e-13 | PASS |
| 37 | R29 365d 1U None / cpn Conditional with Memory/SemiAnnually / AC Issuer Callable/SemiAnnua | 1200 | 2.15e-14 | PASS |
| 38 | R30 365d 2U Worst-Of / cpn Fixed Unconditional/Yearly / AC Variable Barrier/SemiAnnually+N | 1200 | 3.13e-13 | PASS |
| 39 | R31 730d 3U Equally Weighted / cpn None/Yearly / AC Variable Barrier/Monthly+None / KI Non | 1200 | 1.81e-09 | PASS |
| 40 | R32 547d 2U Worst-Of / cpn Fixed Unconditional/At Maturity / AC Variable Barrier/Monthly+N | 1200 | 6.30e-15 | PASS |
| 41 | R33 365d 1U None / cpn Conditional with Memory/SemiAnnually / AC Constant Barrier/Yearly+S | 1200 | 2.13e-14 | PASS |
| 42 | R34 547d 4U Worst-Of / cpn Conditional/SemiAnnually / AC Constant Barrier/Yearly+Flat / KI | 1200 | 2.16e-14 | PASS |
| 43 | R35 547d 2U Worst-Of / cpn Conditional/Quarterly / AC Issuer Callable/Quarterly+None / KI  | 1200 | 1.44e-14 | PASS |
| 44 | R36 365d 1U None / cpn None/At Maturity / AC Constant Barrier/SemiAnnually+None / KI Europ | 1200 | 1.11e-14 | PASS |
| 45 | R37 365d 1U None / cpn Conditional/At Maturity / AC Variable Barrier/SemiAnnually+None / K | 1200 | 9.10e-15 | PASS |
| 46 | R38 547d 1U None / cpn Conditional/SemiAnnually / AC Variable Barrier/SemiAnnually+None /  | 1200 | 1.44e-14 | PASS |
| 47 | R39 730d 1U None / cpn Fixed Unconditional/SemiAnnually / AC Constant Barrier/Yearly+None  | 1200 | 1.03e-14 | PASS |
| 48 | R40 730d 3U Worst-Of / cpn Conditional/SemiAnnually / AC None/Monthly+None / KI European ( | 1200 | 1.19e-14 | PASS |
| 49 | R41 730d 3U Worst-Of / cpn Conditional/Quarterly / AC Constant Barrier/Quarterly+Flat / KI | 1200 | 1.16e-14 | PASS |
| 50 | R42 547d 1U None / cpn Fixed Unconditional/At Maturity / AC Constant Barrier/Quarterly+Non | 1200 | 1.17e-14 | PASS |
| 51 | R43 547d 1U None / cpn None/At Maturity / AC None/Monthly+Flat / KI None 51.28 / solve Put | 1200 | 2.45e-14 | PASS |
| 52 | R44 182d 4U Equally Weighted / cpn Conditional with Memory/Yearly / AC Constant Barrier/Se | 1200 | 8.61e-15 | PASS |
| 53 | R45 365d 2U Equally Weighted / cpn Fixed Unconditional/Yearly / AC Constant Barrier/SemiAn | 1200 | 7.99e-14 | PASS |
| 54 | R46 365d 1U None / cpn Fixed Unconditional/Quarterly / AC Constant Barrier/Yearly+None / K | 1200 | 7.67e-14 | PASS |
| 55 | R47 182d 3U Worst-Of / cpn Fixed Unconditional/At Maturity / AC Issuer Callable/Monthly+Sn | 1200 | 2.93e-14 | PASS |
| 56 | R48 730d 4U Worst-Of / cpn None/SemiAnnually / AC Constant Barrier/Monthly+Flat / KI Ameri | 1200 | 2.77e-14 | PASS |
| 57 | R49 730d 4U Worst-Of / cpn Fixed Unconditional/Monthly / AC Constant Barrier/Quarterly+Fla | 1200 | 1.40e-14 | PASS |
| 58 | R50 365d 1U None / cpn None/Quarterly / AC Variable Barrier/SemiAnnually+None / KI America | 1200 | 7.38e-15 | PASS |

Compared per case: PV, Solved, solvable, legs (bond/coupon/autocall_coupon/put),
risk (p_autocall, expected_life_y, p_knock_in, p_capital_loss, exp_term_worst,
term p05/p50/p95, VaR95/99, ES95/99, p_loss, p_gain, p_maturity), and the
terminal distribution (lo/hi + 40-bin histogram).

