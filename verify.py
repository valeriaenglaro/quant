#!/usr/bin/env python3
"""verify.py -- parity harness: engine.py vs master.k on IDENTICAL normals.

Generates the exact normal draws engine.py will use (numpy seed 42, per-asset
(n_sims, days) matrices) and passes them to master.k via the `_Z` hook, so both
engines price the very same paths. Any residual difference is float roundoff,
NOT Monte-Carlo noise. Compares PV / Solved / legs / risk / dist / greeks.
"""
import json, subprocess, tempfile, shutil, os, sys, copy, math
import numpy as np
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("engine", os.path.join(HERE, "engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)

K_BIN = os.path.join(HERE, "k"); KSCRIPT = os.path.join(HERE, "master.k")

def z_draws(cfg, n):
    nU = len(cfg["data"]["Underlying"]); days = int(cfg["data"]["Days"])
    np.random.seed(42)
    return [np.random.normal(0.0, 1.0, size=(n, days)).tolist() for _ in range(nU)]

def run_k(cfg):
    wd = tempfile.mkdtemp(prefix="kv_")
    try:
        shutil.copy(KSCRIPT, os.path.join(wd, "master.k"))
        json.dump(cfg, open(os.path.join(wd, "json.json"), "w"))
        out = subprocess.run([K_BIN, "master.k"], cwd=wd, capture_output=True, text=True, timeout=600)
        txt = (out.stdout or "").strip()
        if not txt:
            raise RuntimeError("k produced no output: " + (out.stderr or "")[:300])
        return json.loads(json.loads(txt)) if txt.startswith('"') else json.loads(txt)
    finally:
        shutil.rmtree(wd, ignore_errors=True)

def close(a, b, tol):
    if a is None and b is None: return True
    if a is None or b is None: return False
    if isinstance(a, list):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol * (1.0 + max(abs(a), abs(b)))

def cmp(name, py, kk, tol, fails):
    ok = close(py, kk, tol)
    flag = "OK " if ok else "FAIL"
    print("   %s %-22s py=%-24s k=%s" % (flag, name, py, kk))
    if not ok: fails.append(name)

def check(label, cfg, n, greeks=False, tol=1e-6):
    print("== %s (n=%d)" % (label, n))
    cfg = copy.deepcopy(cfg); cfg["n_sims"] = n
    pyc = copy.deepcopy(cfg); pyc["greeks"] = 2 if greeks else 0
    rp = ENG.run(pyc)
    kc = copy.deepcopy(cfg); kc["greeks"] = 3 if greeks else 1
    kc["_Z"] = z_draws(cfg, n)
    rk = run_k(kc)
    fails = []
    cmp("PV", rp["PV"], rk["PV"], tol, fails)
    cmp("Solved", rp["Solved"], rk["Solved"], max(tol, 2e-5), fails)
    cmp("solvable", 1 if rp["solvable"] else 0, 1 if rk["solvable"] else 0, 0, fails)
    for leg in ("bond", "coupon", "autocall_coupon", "put"):
        cmp("legs." + leg, rp["legs"][leg], rk["legs"][leg], tol, fails)
    for kkey in rp["risk"]:
        cmp("risk." + kkey, rp["risk"][kkey], rk["risk"][kkey], tol, fails)
    cmp("dist.lo", rp["dist"]["lo"], rk["dist"]["lo"], tol, fails)
    cmp("dist.hi", rp["dist"]["hi"], rk["dist"]["hi"], tol, fails)
    dc = sum(abs(a - b) for a, b in zip(rp["dist"]["counts"], rk["dist"]["counts"]))
    print("   %s dist.counts |diff|=%d" % ("OK " if dc <= 2 else "FAIL", dc))
    if dc > 2: fails.append("dist.counts")
    if greeks:
        for gk in ("delta", "gamma", "vega", "rho", "delta_per_asset", "vega_per_asset"):
            cmp("greeks." + gk, rp["greeks"][gk], rk["greeks"][gk], max(tol, 1e-5), fails)
    print("   -> %s" % ("ALL MATCH" if not fails else "MISMATCH: " + ", ".join(fails)))
    return fails

BASE = json.load(open(os.path.join(HERE, "json.json")))

def main():
    allf = {}
    t = []

    t.append(("T1 base json.json (solve KI, Worst-Of, FU semiannual, AC const)",
              BASE, 400, False))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"]["KI Barrier (%)"] = 65
    c["data"]["Basket Type"] = "Equally Weighted"
    c["data"]["Barrier Type"] = "American Daily Close"
    c["data"]["Leverage (%)"] = "No"
    c["coupon_config"]["Coupon Type"] = "Conditional with Memory"
    c["coupon_config"]["Coupon Frequency"] = "Quarterly"
    c["coupon_config"]["Coupon (%)"] = 9.0
    c["coupon_config"]["Coupon Barrier Level (%)"] = 70
    for dv in c["data"]["Dividends"]: dv["amount"] = 2.5
    t.append(("T2 price Reoffer, EW basket, CondMemory qtrly, AmerDaily, divs>0", c, 400, False))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Autocall Coupon (%)"
    c["Autocall"]["Type"] = "Variable Barrier"
    c["Autocall"]["Step Up / Down (%)"] = -1.0
    c["Autocall"]["Autocall Frequency"] = "Quarterly"
    c["Autocall"]["Autocallable From"] = "Q2"
    c["Autocall_Coupon"]["Autocall Coupon Type"] = "Snowball"
    c["Autocall_Coupon"]["AC Coupon (%)"] = 8.0
    c["data"]["Barrier Type"] = "European (Maturity)"
    c["data"]["KI Barrier (%)"] = 60
    c["data"]["One Star"] = "Yes"
    c["data"]["One Star Level (%)"] = 95
    t.append(("T3 solve AC coupon, Snowball, VarBarrier step, European, OneStar", c, 400, False))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Coupon (%)"
    c["data"]["Underlying"] = ["MSFT US"]
    c["data"]["Spot Price"] = [357.12]
    c["data"]["Volatility"] = [0.34]
    c["data"]["Skew Beta"] = [0.1]
    c["data"]["Dividends"] = [{"underlying_idx": 0, "amount": 3.0, "days_to_pay": 90}]
    c["data"]["Basket Type"] = "None"
    c["data"]["Barrier Type"] = "None"
    c["data"]["Capital Guaranteed"] = "Yes"
    c["Capital Guarantee Level (%)"] = 95
    c["coupon_config"]["Coupon Type"] = "Fixed Unconditional"
    c["coupon_config"]["Coupon Frequency"] = "At Maturity"
    t.append(("T4 solve Coupon, single asset, CapGuar 95, AtMaturity FU, no barrier", c, 400, False))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Put Strike (%)"
    c["data"]["Underlying"] = ["MSFT US", "NVDA US"]
    c["data"]["Spot Price"] = [357.12, 120.0]
    c["data"]["Volatility"] = [0.30, 0.45]
    c["data"]["Skew Beta"] = [0.1, 0.2]
    c["data"]["Dividends"] = [{"underlying_idx": 0, "amount": 1.0, "days_to_pay": 30},
                              {"underlying_idx": 1, "amount": 0.5, "days_to_pay": 200}]
    c["data"]["KI Barrier (%)"] = 70
    c["data"]["Leverage (%)"] = "150"
    c["Autocall"]["Type"] = "Issuer Callable"
    c["Autocall_Coupon"]["Autocall Coupon Type"] = "Flat"
    c["Autocall_Coupon"]["AC Coupon (%)"] = 10.0
    c["coupon_config"]["Coupon Type"] = "Conditional"
    c["coupon_config"]["Coupon Frequency"] = "Monthly"
    c["coupon_config"]["Coupon (%)"] = 12.0
    c["coupon_config"]["Coupon Barrier Level (%)"] = 80
    t.append(("T5 solve PutStrike, 2 assets, IssuerCallable+Flat (XOR), lev 150", c, 400, False))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"]["Tenor"] = "18M"; c["data"]["Days"] = 547
    c["data"]["KI Barrier (%)"] = 62
    c["Autocall"]["Type"] = "Custom Barrier"
    c["Autocall"]["Autocall Frequency"] = "SemiAnnually"
    c["Autocall"]["Autocall Barrier (%)"] = [102, 100, 98]
    c["coupon_config"]["Coupon Frequency"] = "Yearly"
    c["coupon_config"]["Coupon (%)"] = 10.0
    c["spot_mult"] = [1.01, 1.0, 0.99, 1.0]
    c["vol_add"] = 0.01
    c["rf_add"] = 0.001
    t6 = c

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"]["KI Barrier (%)"] = 65
    t.append(("T7 GREEKS parity (per-asset, CRN), pinned KI=65", c, 150, True))

    c = copy.deepcopy(BASE)
    c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"]["KI Barrier (%)"] = 60.61865190342334   # k-solved value from T1, pinned in BOTH engines
    t.append(("T8 T1's solved KI pinned in both engines (functional identity)", c, 400, False))

    # T6: bump hooks (spot_mult/vol_add/rf_add). engine.py's run() does not read
    # these keys; its equivalent is simulate(...bumps...)+price_legs, which is what
    # the server's greek bump runs rely on. Compare that against master.k flag 0.
    label6 = "T6 547d custom-barrier list + spot_mult/vol_add/rf_add bump hooks"
    print("== " + label6 + " (n=300)")
    try:
        n6 = 300
        c6 = copy.deepcopy(t6); c6["n_sims"] = n6
        nU6 = len(c6["data"]["Underlying"])
        sim = ENG.simulate(c6, n6, spot_mult=c6["spot_mult"],
                           vol_add=[c6["vol_add"]]*nU6, rf_add=c6["rf_add"])
        legs = ENG.price_legs(c6, sim, ENG._base_params(c6))
        pv_py = 100.0 * legs["pnl"].mean() / c6["data"]["Notional"]
        kc6 = copy.deepcopy(c6); kc6["_Z"] = z_draws(c6, n6)   # greeks flag absent -> 0
        rk6 = run_k(kc6)
        f6 = []
        cmp("PV(bumped)", pv_py, rk6["PV"], 1e-6, f6)
        if f6: allf[label6] = f6
        print("   -> %s" % ("ALL MATCH" if not f6 else "MISMATCH"))
    except Exception as e:
        print("   EXCEPTION:", e); allf[label6] = ["exception: %s" % e]
    print()

    for label, cfg, n, gk in t:
        try:
            f = check(label, cfg, n, greeks=gk)
            if f: allf[label] = f
        except Exception as e:
            print("   EXCEPTION:", e); allf[label] = ["exception: %s" % e]
        print()
    print("=" * 60)
    print("RESULT:", "ALL TESTS MATCH" if not allf else json.dumps(allf, indent=1))
    return 0 if not allf else 1

if __name__ == "__main__":
    sys.exit(main())
