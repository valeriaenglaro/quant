#!/usr/bin/env python3
"""compare_engines.py — side-by-side Python vs ngn/k comparison, PRODUCTION mode.

Runs every test case through BOTH engines exactly the way the app does
(each engine generates its own random numbers — no test-only injection).
Because both engines now share the QS portable random stream (Lehmer LCG
48271 mod 2^31-1, seed 42, Box-Muller), they price identical paths and the
answers agree to float round-off.

For every case it prints BOTH engines' answers metric by metric, the
difference in %, and PASS/FAIL against the tolerance (default 1%).

Usage:
    python3 compare_engines.py                    # battery + 40 random cases
    python3 compare_engines.py --random 100
    python3 compare_engines.py --paths 10000 --tol 1.0
    python3 compare_engines.py --quiet            # summary lines only

Outputs: engine_comparison.md and engine_comparison.json (all numbers).
"""
import json, subprocess, tempfile, shutil, os, sys, copy, argparse, random, datetime
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("engine", os.path.join(HERE, "engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)

FREQS = ["Monthly", "Quarterly", "SemiAnnually", "Yearly"]
NAMES = ["MSFT US", "NVDA US", "AAPL US", "GOOG US", "META US", "TSLA US"]


def run_k(kbin, cfg):
    wd = tempfile.mkdtemp(prefix="kc_")
    try:
        shutil.copy(os.path.join(HERE, "master.k"), os.path.join(wd, "master.k"))
        json.dump(cfg, open(os.path.join(wd, "json.json"), "w"))
        out = subprocess.run([kbin, "master.k"], cwd=wd, capture_output=True, text=True, timeout=900)
        txt = (out.stdout or "").strip()
        if not txt:
            raise RuntimeError("k produced no output: " + (out.stderr or "")[:400])
        return json.loads(json.loads(txt)) if txt.startswith('"') else json.loads(txt)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def diff_pct(a, b):
    """difference as % of the larger magnitude (0 if both ~0)."""
    if a is None or b is None:
        return None
    scale = max(abs(a), abs(b))
    if scale < 1e-12:
        return 0.0
    return 100.0 * abs(a - b) / scale


def fmt(v):
    if v is None: return "None"
    return "%.8f" % v


def run_case(kbin, label, cfg, n, tol, quiet):
    cfg = copy.deepcopy(cfg); cfg["n_sims"] = n
    pyc = copy.deepcopy(cfg); pyc["greeks"] = 0
    rp = ENG.run(pyc)
    kc = copy.deepcopy(cfg); kc["greeks"] = 1
    rk = run_k(kbin, kc)

    rows = []
    # Scoring (all values from BOTH engines are always shown):
    #   mode "rel": relative %% difference        - headline answers (PV, Solved)
    #   mode "pts": difference in %%-points        - legs / VaR / ES / terminal stats
    #               (they are quoted in %% of notional; a solve on a barrier is a
    #               step function, so a single marginal path moves a tiny leg by a
    #               large RELATIVE amount while the actual answer moves ~0.01 pts)
    #   mode "prb": difference in probability points (x100)
    def add(name, a, b, mode="rel"):
        if a is None or b is None:
            d = None
        elif mode == "rel":
            d = diff_pct(a, b)
        elif mode == "prb":
            d = 100.0 * abs(a - b)
        else:
            d = abs(a - b)
        ok = (d is not None) and (d <= tol)
        rows.append({"metric": name, "mode": mode, "python": a, "ngnk": b,
                     "diff": d, "diff_pct": d, "pass": bool(ok)})

    add("PV (%)", rp["PV"], rk["PV"], "rel")
    add("Solved [" + cfg["platform"]["Solve for"] + "]", rp["Solved"], rk["Solved"], "rel")
    for leg in ("bond", "coupon", "autocall_coupon", "put"):
        add("leg " + leg + " (%)", rp["legs"][leg], rk["legs"][leg], "pts")
    for k2 in rp["risk"]:
        mode = "prb" if k2.startswith("p_") else ("pts" if k2.endswith("_pct") or k2.startswith(("var", "es", "term", "exp_term", "max")) else "rel")
        add("risk " + k2, rp["risk"][k2], rk["risk"].get(k2), mode)

    ok = all(r["pass"] for r in rows)
    worst = max((r["diff_pct"] or 0.0) for r in rows)
    status = "PASS" if ok else "FAIL"
    print("%s  %-84s worst diff %.2e %%" % (status, label[:84], worst))
    if not quiet:
        print("      %-34s %18s %18s %12s" % ("metric", "python", "ngn/k", "diff %"))
        for r in rows:
            print("      %-34s %18s %18s %12s  %s" %
                  (r["metric"], fmt(r["python"]), fmt(r["ngnk"]),
                   ("%.2e" % r["diff_pct"]) if r["diff_pct"] is not None else "-",
                   "ok" if r["pass"] else "<-- FAIL"))
    return {"label": label, "n": n, "solve": cfg["platform"]["Solve for"],
            "pass": ok, "worst_diff_pct": worst, "rows": rows}


# ----------------------------------------------------------------- cases
def battery():
    van = json.load(open(os.path.join(HERE, "json.json")))
    B4 = {
     "platform": {"Solve for": "KI Barrier (%)", "Issue Price (%)": 100, "Reoffer (%)": 99.5, "Issuer Margin (%)": 1.5},
     "data": {"Underlying": ["MSFT US", "NVDA US", "AAPL US", "GOOG US"],
              "Spot Price": [357.12, 357.12, 357.12, 357.12], "Basket Type": "Worst-Of",
              "Notional": 1000000, "Tenor": "1Y", "Days": 365,
              "Volatility": [0.34, 0.34, 0.34, 0.34], "Skew Beta": [0.1, 0.1, 0.1, 0.1],
              "Risk-Free Rate": 0.0398, "Barrier Type": "American Intraday",
              "KI Barrier (%)": "", "Put Strike (%)": 80, "Leverage (%)": "Yes",
              "One Star": "No", "One Star Level (%)": 100, "Capital Guaranteed": "No",
              "Dividends": [{"underlying_idx": i, "amount": 0, "days_to_pay": 20} for i in range(4)]},
     "coupon_config": {"Coupon Type": "Fixed Unconditional", "Coupon Barrier Level (%)": 0,
                       "Coupon Frequency": "SemiAnnually", "Coupon (%)": 15.737},
     "Autocall": {"Type": "Constant Barrier", "Autocall Frequency": "SemiAnnually",
                  "Autocallable From": "S1", "Autocall Barrier (%)": 100, "Step Up / Down (%)": 0},
     "Autocall_Coupon": {"Autocall Coupon Type": "None", "AC Coupon (%)": 0},
     "n_sims": 10000}
    t = [("B01 vanilla Phoenix (json.json, solve coupon)", van),
         ("B02 4-name worst-of, solve KI barrier", B4)]
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Reoffer (%)"; c["data"]["KI Barrier (%)"] = 65
    c["data"]["Basket Type"] = "Equally Weighted"; c["data"]["Barrier Type"] = "American Daily Close"
    c["coupon_config"].update({"Coupon Type": "Conditional with Memory", "Coupon Frequency": "Quarterly",
                               "Coupon (%)": 9.0, "Coupon Barrier Level (%)": 70})
    for dv in c["data"]["Dividends"]: dv["amount"] = 2.5
    t.append(("B03 EW basket, memory coupon, dividends, price reoffer", c))
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Autocall Coupon (%)"
    c["Autocall"].update({"Type": "Variable Barrier", "Step Up / Down (%)": -1.0,
                          "Autocall Frequency": "Quarterly", "Autocallable From": "Q2"})
    c["Autocall_Coupon"] = {"Autocall Coupon Type": "Snowball", "AC Coupon (%)": 8.0}
    c["data"].update({"Barrier Type": "European (Maturity)", "KI Barrier (%)": 60,
                      "One Star": "Yes", "One Star Level (%)": 95})
    t.append(("B04 snowball, variable barrier, one-star, solve AC coupon", c))
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Coupon (%)"
    c["data"].update({"Underlying": ["MSFT US"], "Spot Price": [357.12], "Volatility": [0.34],
                      "Skew Beta": [0.1], "Basket Type": "None", "Barrier Type": "None",
                      "Capital Guaranteed": "Yes",
                      "Dividends": [{"underlying_idx": 0, "amount": 3.0, "days_to_pay": 90}]})
    c["Capital Guarantee Level (%)"] = 95
    c["coupon_config"].update({"Coupon Type": "Fixed Unconditional", "Coupon Frequency": "At Maturity"})
    t.append(("B05 capital-guaranteed 95, at-maturity coupon", c))
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"].update({"Tenor": "18M", "Days": 547, "KI Barrier (%)": 62})
    c["Autocall"].update({"Type": "Custom Barrier", "Autocall Frequency": "SemiAnnually",
                          "Autocall Barrier (%)": [102, 100, 98]})
    c["coupon_config"].update({"Coupon Frequency": "Yearly", "Coupon (%)": 10.0})
    t.append(("B06 18M custom barrier schedule", c))
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Coupon (%)"; c["Autocall"]["Type"] = "None"
    c["data"].update({"Underlying": ["AAPL US"], "Spot Price": [299.56], "Volatility": [0.222],
                      "Skew Beta": [0.15], "Basket Type": "None",
                      "Barrier Type": "American Daily Close", "KI Barrier (%)": 70, "Put Strike (%)": 100,
                      "Dividends": [{"underlying_idx": 0, "amount": 0, "days_to_pay": 20}]})
    c["coupon_config"].update({"Coupon Type": "Fixed Unconditional", "Coupon Frequency": "Quarterly",
                               "Coupon (%)": ""})
    t.append(("B07 reverse convertible (no autocall), solve coupon", c))
    c = copy.deepcopy(B4); c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"].update({"Tenor": "2Y", "Days": 730, "KI Barrier (%)": 55})
    c["Autocall"].update({"Autocall Frequency": "Monthly", "Autocallable From": "M6"})
    c["coupon_config"].update({"Coupon Type": "Conditional", "Coupon Frequency": "Monthly",
                               "Coupon (%)": 7.5, "Coupon Barrier Level (%)": 65})
    t.append(("B08 2Y monthly autocall from M6", c))
    return t


def random_case(rng, i):
    nU = rng.choice([1, 1, 2, 3, 4])
    days = rng.choice([182, 365, 365, 547, 730])
    tenor = {182: "6M", 365: "1Y", 547: "18M", 730: "2Y"}[days]
    und = rng.sample(NAMES, nU)
    ac_type = rng.choice(["Constant Barrier", "Constant Barrier", "Variable Barrier", "Issuer Callable", "None"])
    acc_type = rng.choice(["None", "None", "Snowball", "Flat"])
    cpn_type = rng.choice(["Fixed Unconditional", "Conditional", "Conditional with Memory", "None"])
    cpn_freq = rng.choice(FREQS + ["At Maturity"])
    barrier = rng.choice(["European (Maturity)", "American Daily Close", "American Intraday", "None"])
    solve = rng.choice(["Reoffer (%)", "Reoffer (%)", "Coupon (%)", "KI Barrier (%)",
                        "Put Strike (%)", "Autocall Coupon (%)"])
    if solve == "Autocall Coupon (%)":
        if ac_type in ("None", "Issuer Callable"): ac_type = "Constant Barrier"
        if acc_type == "None": acc_type = rng.choice(["Snowball", "Flat"])
    if solve == "Coupon (%)":
        if cpn_type == "None": cpn_type = "Fixed Unconditional"
        acc_type = "None"
    if solve == "KI Barrier (%)" and barrier == "None":
        barrier = "American Daily Close"
    fromu = {"Monthly": "M", "Quarterly": "Q", "SemiAnnually": "S", "Yearly": "Y"}
    ac_freq = rng.choice(FREQS)
    cfg = {
      "platform": {"Solve for": solve, "Issue Price (%)": 100,
                   "Reoffer (%)": round(rng.uniform(97.0, 100.0), 2),
                   "Issuer Margin (%)": round(rng.uniform(0.5, 2.0), 2)},
      "data": {"Underlying": und, "Spot Price": [round(rng.uniform(20, 500), 2) for _ in range(nU)],
               "Basket Type": ("None" if nU == 1 else rng.choice(["Worst-Of", "Worst-Of", "Equally Weighted"])),
               "Notional": rng.choice([1000000, 5000000, 250000]), "Tenor": tenor, "Days": days,
               "Volatility": [round(rng.uniform(0.15, 0.6), 3) for _ in range(nU)],
               "Skew Beta": [round(rng.uniform(0.0, 0.3), 2) for _ in range(nU)],
               "Risk-Free Rate": round(rng.uniform(0.0, 0.06), 4),
               "Barrier Type": barrier,
               "KI Barrier (%)": ("" if solve == "KI Barrier (%)" else round(rng.uniform(50, 80), 2)),
               "Put Strike (%)": ("" if solve == "Put Strike (%)" else rng.choice([80, 90, 100])),
               "Leverage (%)": rng.choice(["Yes", "No", "125", "150"]),
               "One Star": rng.choice(["No", "No", "No", "Yes"]),
               "One Star Level (%)": rng.choice([95, 100]),
               "Capital Guaranteed": rng.choice(["No"] * 9 + ["Yes"]),
               "Dividends": [{"underlying_idx": j,
                              "amount": round(rng.choice([0, 0, rng.uniform(0.5, 4.0)]), 2),
                              "days_to_pay": rng.randrange(10, days - 5)} for j in range(nU)]},
      "coupon_config": {"Coupon Type": cpn_type,
                        "Coupon Barrier Level (%)": round(rng.uniform(50, 85), 1),
                        "Coupon Frequency": cpn_freq,
                        "Coupon (%)": ("" if solve == "Coupon (%)" else round(rng.uniform(3, 16), 3))},
      "Autocall": {"Type": ac_type, "Autocall Frequency": ac_freq,
                   "Autocallable From": fromu[ac_freq] + str(rng.choice([1, 1, 2])),
                   "Autocall Barrier (%)": rng.choice([95, 100, 100, 105]),
                   "Step Up / Down (%)": (round(rng.uniform(-2, 1), 2) if ac_type == "Variable Barrier" else 0)},
      "Autocall_Coupon": {"Autocall Coupon Type": acc_type,
                          "AC Coupon (%)": ("" if solve == "Autocall Coupon (%)" else round(rng.uniform(4, 12), 2))}}
    lbl = ("R%02d %dd %dU %s | cpn %s/%s | AC %s/%s+%s | KI %s %s | solve %s" %
           (i, days, nU, cfg["data"]["Basket Type"], cpn_type, cpn_freq, ac_type, ac_freq,
            acc_type, barrier, cfg["data"]["KI Barrier (%)"], solve))
    return lbl, cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=40)
    ap.add_argument("--paths", type=int, default=2000, help="paths for random cases (battery uses 10000)")
    ap.add_argument("--tol", type=float, default=1.0, help="max allowed difference: rel-%% / %%-points / prob-points (default 1)")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--kbin", default=os.path.join(HERE, "k"))
    ap.add_argument("--quiet", action="store_true", help="summary line per case only")
    ap.add_argument("--out", default="engine_comparison")
    a = ap.parse_args()

    cases = [(lbl, cfg, 10000) for lbl, cfg in battery()]
    rng = random.Random(a.seed)
    for i in range(1, a.random + 1):
        lbl, cfg = random_case(rng, i)
        cases.append((lbl, cfg, a.paths))

    results = []
    for label, cfg, n in cases:
        try:
            results.append(run_case(a.kbin, label, cfg, n, a.tol, a.quiet))
        except Exception as e:
            print("FAIL  %-84s EXCEPTION: %s" % (label[:84], e))
            results.append({"label": label, "n": n, "pass": False,
                            "worst_diff_pct": None, "rows": [], "error": str(e)})
    npass = sum(r["pass"] for r in results)
    worst = max((r["worst_diff_pct"] or 0.0) for r in results if r.get("worst_diff_pct") is not None)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    md = ["# Python vs ngn/k — side-by-side comparison (PRODUCTION mode)",
          "", "Run: %s · tolerance %.3g%% · both engines generate their own randoms" % (stamp, a.tol),
          "(shared QS stream: Lehmer LCG 48271 mod 2^31-1, seed 42, Box-Muller).",
          "", "**%d / %d cases PASS · worst difference anywhere: %.2e %%**" % (npass, len(results), worst), ""]
    for r in results:
        md.append("## %s  —  %s" % (("PASS" if r["pass"] else "FAIL"), r["label"].replace("|", "/")))
        md.append("")
        if r.get("error"):
            md.append("EXCEPTION: " + r["error"]); md.append(""); continue
        md.append("| metric | python | ngn/k | diff % | ok |")
        md.append("|--------|--------|-------|--------|----|")
        for row in r["rows"]:
            md.append("| %s | %s | %s | %s | %s |" % (
                row["metric"], fmt(row["python"]), fmt(row["ngnk"]),
                ("%.2e" % row["diff_pct"]) if row["diff_pct"] is not None else "-",
                "yes" if row["pass"] else "**NO**"))
        md.append("")
    open(a.out + ".md", "w").write("\n".join(md) + "\n")
    json.dump({"generated": stamp, "tolerance_pct": a.tol, "pass": npass, "total": len(results),
               "worst_diff_pct": worst, "results": results},
              open(a.out + ".json", "w"), indent=1, default=float)
    print("\n%s: %d/%d PASS · worst diff %.2e %% (tolerance %.3g%%) -> %s.md / %s.json"
          % ("ALL GREEN" if npass == len(results) else "RED", npass, len(results), worst, a.tol, a.out, a.out))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())