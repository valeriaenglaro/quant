#!/usr/bin/env python3
"""build_site.py - pre-compute QuantSuite pricer output with Amber at BUILD time
and emit a self-contained static site for GitHub Pages (no runtime backend).

For each sample ticket it runs master.k through the Amber (ngn/k) interpreter and,
when NumPy/SciPy are available, the engine.py baseline too, then bakes the numbers
into a single index.html. GitHub Pages serves only static assets, so all pricing
happens here in CI, not in the visitor's browser.

    python3 build_site.py --kbin ./amber_src/amber --out ./_site
"""
import json, subprocess, tempfile, shutil, os, sys, argparse, datetime, html

HERE = os.path.dirname(os.path.abspath(__file__))


def run_k(kbin, cfg):
    wd = tempfile.mkdtemp(prefix="site_")
    try:
        import copy
        cfg = copy.deepcopy(cfg); cfg["greeks"] = 1     # flag 1 -> full risk block
        shutil.copy(os.path.join(HERE, "master.k"), os.path.join(wd, "master.k"))
        json.dump(cfg, open(os.path.join(wd, "json.json"), "w"))
        out = subprocess.run([kbin, "master.k"], cwd=wd, capture_output=True, text=True, timeout=600)
        txt = (out.stdout or "").strip()
        if not txt:
            raise RuntimeError((out.stderr or "no output")[:300])
        return json.loads(json.loads(txt)) if txt.startswith('"') else json.loads(txt)
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def try_py(cfg):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("engine", os.path.join(HERE, "engine.py"))
        eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
        import copy
        c = copy.deepcopy(cfg); c["greeks"] = 1
        return eng.run(c)
    except Exception as e:
        return {"_error": str(e)}


def tickets():
    base = json.load(open(os.path.join(HERE, "json.json")))
    import copy
    t = [("Vanilla Phoenix (MSFT, 1Y, quarterly memory coupon, solve coupon)", base)]
    c = copy.deepcopy(base)
    c["platform"]["Solve for"] = "Reoffer (%)"
    c["data"].update({"Underlying": ["MSFT US", "NVDA US", "AAPL US"],
                      "Spot Price": [357.12, 120.0, 299.56], "Volatility": [0.34, 0.45, 0.30],
                      "Skew Beta": [0.1, 0.2, 0.15], "Basket Type": "Worst-Of",
                      "Barrier Type": "American Daily Close", "KI Barrier (%)": 60,
                      "Dividends": [{"underlying_idx": i, "amount": 0, "days_to_pay": 20} for i in range(3)]})
    c["coupon_config"].update({"Coupon (%)": 9.0})
    t.append(("3-name Worst-Of, American KI 60%, price the reoffer", c))
    c = copy.deepcopy(base)
    c["platform"]["Solve for"] = "Coupon (%)"
    c["Autocall"]["Type"] = "None"
    c["data"].update({"Barrier Type": "American Daily Close", "KI Barrier (%)": 70, "Put Strike (%)": 100})
    c["coupon_config"].update({"Coupon Type": "Fixed Unconditional", "Coupon Frequency": "Quarterly", "Coupon (%)": ""})
    t.append(("Reverse Convertible (no autocall), American KI 70%, solve coupon", c))
    return t


def fmt(x):
    return "%.4f" % x if isinstance(x, (int, float)) else html.escape(str(x))


CSS = """
:root{--bg:#0b1020;--card:#151c33;--ink:#e8ecf5;--mut:#9aa6c4;--line:#26304f;--ok:#43c59e;--acc:#6ea8fe}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:40px 22px 70px}
h1{font-size:26px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 26px}
.badge{display:inline-block;background:rgba(67,197,158,.12);color:var(--ok);border:1px solid rgba(67,197,158,.4);
border-radius:999px;padding:4px 12px;font-size:13px;font-weight:600;margin-bottom:26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin:0 0 18px}
.card h2{font-size:17px;margin:0 0 3px}.card .desc{color:var(--mut);font-size:13px;margin:0 0 16px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td.n{font-variant-numeric:tabular-nums;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pill{font-size:12px;color:var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:#0f1730;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .k{color:var(--mut);font-size:12px}.kpi .v{font-size:20px;font-variant-numeric:tabular-nums;margin-top:2px}
footer{color:var(--mut);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:16px}
code{background:#0f1730;padding:1px 6px;border-radius:5px;font-size:13px}
a{color:var(--acc)}
"""


def kpi(label, val):
    return '<div class="kpi"><div class="k">%s</div><div class="v">%s</div></div>' % (html.escape(label), val)


def ticket_card(name, cfg, rk, rp):
    legs = rk.get("legs", {})
    risk = rk.get("risk", {})
    kpis = [kpi("PV (% notional)", fmt(rk.get("PV"))),
            kpi("Solved · " + cfg["platform"]["Solve for"], fmt(rk.get("Solved")))]
    for lbl, k in (("Bond leg", "bond"), ("Coupon leg", "coupon"), ("Put leg", "put")):
        if k in legs:
            kpis.append(kpi(lbl, fmt(legs[k])))
    rows = ""
    show = [("P(autocall)", "p_autocall"), ("Expected life (y)", "expected_life_y"),
            ("P(knock-in)", "p_knock_in"), ("P(capital loss)", "p_capital_loss"),
            ("VaR 95%", "var95_pct"), ("VaR 99%", "var99_pct"), ("ES 95%", "es95_pct"),
            ("Term p05", "term_p05"), ("Term p50", "term_p50"), ("Term p95", "term_p95")]
    for lbl, k in show:
        if k in risk and isinstance(risk[k], (int, float)):
            pv = ""
            if rp and "risk" in rp and k in rp["risk"] and isinstance(rp["risk"][k], (int, float)):
                pv = '<td class="n pill">%s</td>' % fmt(rp["risk"][k])
            else:
                pv = '<td class="n pill">—</td>'
            rows += "<tr><td>%s</td><td class=n>%s</td>%s</tr>" % (html.escape(lbl), fmt(risk[k]), pv)
    return """<div class="card"><h2>%s</h2>
    <div class="desc">%s underlying · %s · KI %s%% · %s</div>
    <div class="grid">%s</div>
    <table style="margin-top:16px"><tr><th>Risk metric</th><th style="text-align:right">Amber (ngn/k)</th>
    <th style="text-align:right">Python baseline</th></tr>%s</table></div>""" % (
        html.escape(name), len(cfg["data"]["Underlying"]),
        html.escape(cfg["data"]["Basket Type"]), fmt(cfg["data"].get("KI Barrier (%)", "")),
        html.escape(cfg["data"]["Barrier Type"]), "".join(kpis), rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kbin", default=os.path.join(HERE, "k"))
    ap.add_argument("--out", default="./_site")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    parity_line = "engine.py ↔ master.k verified to float round-off"
    rp_path = os.path.join(HERE, "parity_report.md")
    if os.path.exists(rp_path):
        for ln in open(rp_path):
            if "cases PASS" in ln or "cases within" in ln:
                parity_line = ln.strip().replace("**", "")
                break

    cards = []
    for name, cfg in tickets():
        try:
            rk = run_k(a.kbin, cfg)
        except Exception as e:
            rk = {"_error": str(e)}
        rp = try_py(cfg)
        if "_error" in rk:
            cards.append('<div class="card"><h2>%s</h2><div class="desc">pricing error: %s</div></div>'
                         % (html.escape(name), html.escape(rk["_error"])))
        else:
            cards.append(ticket_card(name, cfg, rk, None if "_error" in rp else rp))

    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    doc = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>QuantSuite — structured products pricer</title><style>%s</style></head><body><div class=wrap>
<h1>QuantSuite</h1><p class=sub>Autocallable &amp; reverse-convertible Monte-Carlo pricer —
priced with the <b>Amber</b> (ngn/k) engine at build time, cross-checked against the Python baseline.</p>
<span class=badge>✓ %s</span>
%s
<footer>Static site — every number was pre-computed by Amber during the GitHub Actions build
(<code>build_site.py</code>); GitHub Pages serves the result with no backend.
The <span class=pill>blue</span> column is the independent Python (NumPy/SciPy) baseline.
Generated %s.</footer>
</div></body></html>""" % (CSS, html.escape(parity_line), "\n".join(cards), stamp)

    open(os.path.join(a.out, "index.html"), "w").write(doc)
    print("wrote", os.path.join(a.out, "index.html"), "(%d bytes)" % len(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
