#!/usr/bin/env python3
"""
server.py — QuantSuite production API (Flask), built for Render.com.

Primary endpoint
    POST /api/price
        Body is either a full pricing config (platform/data/coupon_config/…,
        the shape master.k reads from json.json) OR a small set of convenience
        fields (paths, tickers, spots, vols, coupon, ki_barrier, …) that are
        merged onto a sane default ticket. The handler writes json.json into a
        private temp dir, executes the compiled native **Amber** (ngn/k) binary
        `amber_bin master.k` via subprocess, and returns the parsed JSON result
        (PV, Solved, legs, risk, greeks, timing).

Engine resolution
    Native Amber binary preferred (AMBER_BIN / ./amber_bin / ./k / $PATH). If no
    binary is runnable (e.g. local dev before `docker build`), the request
    transparently falls back to the in-process Python baseline engine.py.

Backward compatibility
    /full /price /margin /health are preserved so the existing terminal
    (index.html) keeps working when it points SRV_BASE at this service.

CORS
    Cross-origin POSTs from https://valeriaenglaro.github.io and localhost are
    accepted (flask-cors).

Run
    dev:  python3 server.py                     # binds $PORT (default 8002)
    prod: gunicorn server:app --bind 0.0.0.0:$PORT
"""
import os, re, sys, json, time, copy, shutil, tempfile, subprocess, importlib.util

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# --------------------------------------------------------------------------- #
# Paths / resources
# --------------------------------------------------------------------------- #
BASE = os.path.dirname(os.path.abspath(__file__))


def _res(name):
    return os.path.join(BASE, name)


KSCRIPT = os.environ.get("KSCRIPT", _res("master.k"))
PORT = int(os.environ.get("PORT", "8002"))
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "300"))

AMBER_ERR = ""


def _find_amber():
    """Locate a runnable native K interpreter. In the Render container the
    Dockerfile builds /app/amber_bin; locally we also accept the bundled ./k."""
    global AMBER_ERR
    cands = [os.environ.get("AMBER_BIN"), os.environ.get("K_BIN"),
             _res("amber_bin"), "/app/amber_bin",
             _res("k"), _res(os.path.join("k_source", "k")),
             shutil.which("amber_bin"), shutil.which("amber"), shutil.which("k")]
    for c in cands:
        if c and os.path.isfile(c):
            c = os.path.abspath(c)
            if not os.access(c, os.X_OK):
                try:
                    os.chmod(c, 0o755)
                except Exception:
                    pass
            if os.access(c, os.X_OK):
                return c
    AMBER_ERR = "no runnable Amber/k binary found (looked for amber_bin, /app/amber_bin, k)."
    return None


AMBER_BIN = _find_amber()

# In-process Python baseline (fallback + margin). engine.py is never modified.
try:
    _spec = importlib.util.spec_from_file_location("engine", _res("engine.py"))
    PYENG = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(PYENG)
    PY_OK = True
except Exception as e:                                   # pragma: no cover
    PYENG, PY_OK = None, False
    print("python engine load failed:", e, file=sys.stderr)


def _amber_runnable():
    global AMBER_ERR
    if not AMBER_BIN or not os.path.exists(KSCRIPT):
        AMBER_ERR = AMBER_ERR or "master.k not found"
        return False
    try:
        r = run_amber({"platform": {"Solve for": "Reoffer (%)", "Issue Price (%)": 100,
                                     "Reoffer (%)": 99.5, "Issuer Margin (%)": 1.5},
                       "data": {"Underlying": ["A"], "Spot Price": [100], "Basket Type": "None",
                                "Notional": 1000000, "Tenor": "1Y", "Days": 365, "Volatility": [0.2],
                                "Skew Beta": [0.1], "Risk-Free Rate": 0.03, "Barrier Type": "None",
                                "KI Barrier (%)": 70, "Put Strike (%)": 100, "Leverage (%)": "No",
                                "One Star": "No", "One Star Level (%)": 100, "Capital Guaranteed": "No",
                                "Dividends": [{"underlying_idx": 0, "amount": 0, "days_to_pay": 180}]},
                       "coupon_config": {"Coupon Type": "None", "Coupon Barrier Level (%)": 0,
                                         "Coupon Frequency": "Yearly", "Coupon (%)": 5},
                       "Autocall": {"Type": "None", "Autocall Frequency": "Quarterly",
                                    "Autocallable From": "Q1", "Autocall Barrier (%)": 100,
                                    "Step Up / Down (%)": 0},
                       "Autocall_Coupon": {"Autocall Coupon Type": "None", "AC Coupon (%)": 0},
                       "n_sims": 500})
        return "PV" in r
    except Exception as e:
        AMBER_ERR = "amber probe failed: %s" % e
        return False


# --------------------------------------------------------------------------- #
# Flask app + CORS
# --------------------------------------------------------------------------- #
app = Flask(__name__)

_ALLOWED_ORIGINS = [
    "https://valeriaenglaro.github.io",
    re.compile(r"^https?://localhost(:\d+)?$"),
    re.compile(r"^https?://127\.0\.0\.1(:\d+)?$"),
]
# Set ALLOW_ALL_ORIGINS=1 to open the API to any origin (public demo mode).
if os.environ.get("ALLOW_ALL_ORIGINS") == "1":
    _ALLOWED_ORIGINS = "*"
CORS(app, resources={r"/*": {"origins": _ALLOWED_ORIGINS}},
     methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type"])


# --------------------------------------------------------------------------- #
# Config building
# --------------------------------------------------------------------------- #
DEFAULT_TICKET = {
    "platform": {"Solve for": "Coupon (%)", "Issue Price (%)": 100, "Reoffer (%)": 99.5,
                 "Issuer Margin (%)": 1.5},
    "data": {"Underlying": ["MSFT US"], "Spot Price": [357.12], "Basket Type": "None",
             "Notional": 1000000, "Tenor": "1Y", "Days": 365, "Volatility": [0.34],
             "Skew Beta": [0.1], "Risk-Free Rate": 0.0398, "Barrier Type": "European (Maturity)",
             "KI Barrier (%)": 60, "Put Strike (%)": 100, "Leverage (%)": "Yes", "One Star": "No",
             "One Star Level (%)": 100, "Capital Guaranteed": "No",
             "Dividends": [{"underlying_idx": 0, "amount": 0, "days_to_pay": 20}]},
    "coupon_config": {"Coupon Type": "Conditional with Memory", "Coupon Barrier Level (%)": 70,
                      "Coupon Frequency": "Quarterly", "Coupon (%)": ""},
    "Autocall": {"Type": "Constant Barrier", "Autocall Frequency": "Quarterly",
                 "Autocallable From": "Q1", "Autocall Barrier (%)": 100, "Step Up / Down (%)": 0},
    "Autocall_Coupon": {"Autocall Coupon Type": "None", "AC Coupon (%)": 0},
    "n_sims": 10000,
}

# convenience field -> (section, key). section None means top-level config key.
_SIMPLE = {
    "paths": (None, "n_sims"), "n_sims": (None, "n_sims"), "greeks": (None, "greeks"),
    "solve_for": ("platform", "Solve for"), "reoffer": ("platform", "Reoffer (%)"),
    "issue_price": ("platform", "Issue Price (%)"), "margin": ("platform", "Issuer Margin (%)"),
    "notional": ("data", "Notional"), "rate": ("data", "Risk-Free Rate"),
    "basket": ("data", "Basket Type"), "barrier_type": ("data", "Barrier Type"),
    "ki_barrier": ("data", "KI Barrier (%)"), "put_strike": ("data", "Put Strike (%)"),
    "leverage": ("data", "Leverage (%)"), "one_star": ("data", "One Star"),
    "coupon": ("coupon_config", "Coupon (%)"), "coupon_type": ("coupon_config", "Coupon Type"),
    "coupon_freq": ("coupon_config", "Coupon Frequency"),
    "coupon_barrier": ("coupon_config", "Coupon Barrier Level (%)"),
    "autocall_type": ("Autocall", "Type"), "autocall_barrier": ("Autocall", "Autocall Barrier (%)"),
    "autocall_freq": ("Autocall", "Autocall Frequency"), "autocall_from": ("Autocall", "Autocallable From"),
    "ac_coupon": ("Autocall_Coupon", "AC Coupon (%)"), "ac_coupon_type": ("Autocall_Coupon", "Autocall Coupon Type"),
}


def _as_list(v):
    return v if isinstance(v, list) else [v]


def build_config(body):
    """Accept a full config (has 'platform' & 'data') OR a flat convenience body,
    and return a complete config dict master.k / engine.py can price."""
    body = body or {}
    if isinstance(body.get("config"), dict):
        base = copy.deepcopy(body["config"])
        rest = {k: v for k, v in body.items() if k != "config"}
    elif "platform" in body and "data" in body:
        base = copy.deepcopy(body)
        rest = {}
    else:
        base, rest = copy.deepcopy(DEFAULT_TICKET), body

    for k in ("platform", "data", "coupon_config", "Autocall", "Autocall_Coupon"):
        base.setdefault(k, copy.deepcopy(DEFAULT_TICKET[k]))

    # underlyings / vectors
    tickers = rest.get("tickers") or rest.get("underlyings") or rest.get("underlying")
    if tickers is not None:
        tickers = _as_list(tickers)
        nU = len(tickers)
        base["data"]["Underlying"] = tickers
        base["data"]["Spot Price"] = _as_list(rest.get("spots") or rest.get("spot") or [100.0] * nU)[:nU] or [100.0] * nU
        base["data"]["Volatility"] = _as_list(rest.get("vols") or rest.get("vol") or [0.30] * nU)[:nU] or [0.30] * nU
        base["data"]["Skew Beta"] = _as_list(rest.get("skews") or rest.get("skew") or [0.10] * nU)[:nU] or [0.10] * nU
        base["data"]["Dividends"] = [{"underlying_idx": i, "amount": 0, "days_to_pay": 180} for i in range(nU)]
        if nU > 1 and base["data"].get("Basket Type", "None") == "None":
            base["data"]["Basket Type"] = "Worst-Of"

    # tenor in days (keep Tenor label roughly in sync)
    days = rest.get("tenor_days") or rest.get("days")
    if days is not None:
        base["data"]["Days"] = int(days)
        base["data"]["Tenor"] = {182: "6M", 365: "1Y", 547: "18M", 730: "2Y"}.get(int(days), "%dD" % int(days))

    # simple scalar overrides
    for field, (sect, key) in _SIMPLE.items():
        if field in rest and rest[field] is not None:
            if sect is None:
                base[key] = rest[field]
            else:
                base.setdefault(sect, {})[key] = rest[field]

    base["n_sims"] = int(base.get("n_sims", 10000))
    return base


# --------------------------------------------------------------------------- #
# Engine execution
# --------------------------------------------------------------------------- #
def run_amber(cfg):
    """Execute the native Amber binary on master.k in a private temp dir."""
    if not AMBER_BIN:
        raise RuntimeError(AMBER_ERR or "amber binary unavailable")
    wd = tempfile.mkdtemp(prefix="amber_")
    try:
        kdir = os.path.dirname(os.path.abspath(KSCRIPT))
        for item in os.listdir(kdir):                       # copy .k payloads only
            if item.endswith(".k"):
                shutil.copy(os.path.join(kdir, item), os.path.join(wd, item))
        with open(os.path.join(wd, "json.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg) + "\n")                 # trailing \n: ngn/k read op
        t0 = time.perf_counter()
        out = subprocess.run([AMBER_BIN, os.path.basename(KSCRIPT)], cwd=wd,
                             capture_output=True, text=True, timeout=RUN_TIMEOUT)
        ms = (time.perf_counter() - t0) * 1000.0
        txt = (out.stdout or "").strip()
        if not txt:
            raise RuntimeError("amber exit %s, no stdout. stderr: %s"
                               % (out.returncode, (out.stderr or "(empty)")[:400]))
        r = json.loads(json.loads(txt)) if txt.startswith('"') else json.loads(txt)
        r["ms"] = round(ms, 2)
        return r
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def price(cfg, engine="amber", detail=1):
    """detail/greeks: 0 legs+risk only, 1 +basket greeks, 2 +per-asset greeks.
    Native Amber maps this to master.k's greeks flag (1/2/3)."""
    cfg = copy.deepcopy(cfg)
    cfg.pop("margin", None)          # pricing is margin-agnostic: a `margin` key
                                     # would make master.k emit the margin dict
    d = int(detail)
    want_native = str(engine).lower() in ("amber", "k", "native", "ngnk", "ngn/k")
    if want_native and AMBER_BIN and _AMBER_OK:
        cfg.pop("greeks", None)
        cfg["greeks"] = 1 if d <= 0 else (2 if d == 1 else 3)
        r = run_amber(cfg)
        r["engine"] = "amber"
        return r
    if not PY_OK:
        raise RuntimeError("no engine available (amber binary missing and python engine failed to load)")
    cfg["greeks"] = max(0, d)
    t0 = time.perf_counter()
    r = PYENG.run(cfg)
    r["ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    r["engine"] = "python"
    return r


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.post("/api/price")
def api_price():
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        return jsonify({"error": "bad JSON: %s" % e}), 400
    try:
        cfg = build_config(body)
        engine = body.get("engine", "amber")
        detail = int(body.get("greeks", body.get("detail", 1)))
        result = price(cfg, engine=engine, detail=detail)
        return jsonify(result)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "pricing timed out — reduce Monte Carlo paths"}), 504
    except Exception as e:
        app.logger.exception("pricing failed")
        return jsonify({"error": str(e)}), 500


@app.get("/api/health")
@app.get("/health")
def health():
    return jsonify({"ok": True, "amber": _AMBER_OK, "python": PY_OK,
                    "amber_bin": AMBER_BIN or "", "amber_error": ("" if _AMBER_OK else AMBER_ERR),
                    "script": os.path.basename(KSCRIPT)})


@app.get("/")
def root():
    return jsonify({"service": "quantsuite-api", "status": "ok",
                    "endpoints": ["POST /api/price", "GET /health"],
                    "engine": "amber" if _AMBER_OK else "python"})


# ---- backward-compatible endpoints for the existing terminal (index.html) ----
@app.post("/full")
def compat_full():
    body = request.get_json(force=True, silent=True) or {}
    engine = request.args.get("engine", "python")
    detail = int(request.args.get("d", "1"))
    eng = "amber" if engine in ("k", "amber") else "python"
    try:
        return jsonify(price(build_config(body) if "platform" not in body else body, eng, detail))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/price")
def compat_price():
    body = request.get_json(force=True, silent=True) or {}
    engine = request.args.get("engine", "python")
    eng = "amber" if engine in ("k", "amber") else "python"
    try:
        return jsonify(price(build_config(body) if "platform" not in body else body, eng, 0))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/margin")
def compat_margin():
    body = request.get_json(force=True, silent=True) or {}
    cfg = body if "platform" in body else build_config(body)
    engine = request.args.get("engine", "amber")
    want_native = str(engine).lower() in ("amber", "k", "native", "ngnk", "ngn/k")
    try:
        # Margin now runs natively in Amber (master.k) as well as in engine.py,
        # with a bit-for-bit identical JSON contract. Route to whichever the
        # caller selected; fall back to the other engine if it is unavailable.
        if want_native and AMBER_BIN and _AMBER_OK:
            mcfg = copy.deepcopy(cfg)
            mcfg["greeks"] = 3                       # margin needs full greeks
            mcfg.setdefault("margin", cfg.get("margin", {}))
            return jsonify(run_amber(mcfg))          # master.k emits the margin dict
        if not PY_OK:
            return jsonify({"error": "no engine available for margin"}), 500
        base = price(copy.deepcopy(cfg), "python", max(1, int(request.args.get("d", "2"))))
        return jsonify(PYENG.compute_margin(base, cfg, cfg.get("margin", {})))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# probe the interpreter once at import time (after run_amber is defined)
_AMBER_OK = _amber_runnable()


def main():
    print("QuantSuite API  ->  http://0.0.0.0:%d" % PORT)
    print("  amber=%s (%s)   python=%s" % (_AMBER_OK, AMBER_BIN or "not found", PY_OK))
    if not _AMBER_OK:
        print("  native engine disabled: %s" % (AMBER_ERR or "unknown"))
    app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
