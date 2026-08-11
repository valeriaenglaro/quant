/* ==========================================================================
 * QuantSuite — frontend client (app.js), 100% CLIENT-SIDE.
 *
 * All pricing runs in the browser via Amber compiled to WebAssembly
 * (amber-wasm.js + amber.wasm). There are NO server calls: no fetch to a
 * backend, no CORS, no Render cold start. Load this AFTER amber-wasm.js.
 *
 * Public API (unchanged signatures, so index.html stays compatible):
 *     await QuantSuite.price(params)              -> result JSON
 *     QuantSuite.priceWithUI(params, ui)          -> Promise<result JSON>
 *
 * `params` is either a flat convenience object (tickers/spots/vols/coupon/
 * ki_barrier/paths/solve_for/greeks/…) or a full config
 * ({platform,data,coupon_config,Autocall,Autocall_Coupon}).
 * ======================================================================== */
(function (global) {
  "use strict";

  var QuantSuite = {
    DEFAULT_PATHS: 2000,   // balance of speed (~300 ms) and Monte-Carlo accuracy
    _initStarted: false,
  };

  // Kick off WASM load as early as possible (idempotent).
  function ensureInit() {
    if (!global.AmberWASM) throw new Error("amber-wasm.js must be loaded before app.js");
    if (!QuantSuite._initStarted) {
      QuantSuite._initStarted = true;
      QuantSuite.ready = global.AmberWASM.init({ wasmUrl: "amber.wasm", masterUrl: "master.k" });
    }
    return QuantSuite.ready;
  }

  // ---- config building: flat convenience fields -> full master.k config ---- //
  var DEFAULT_TICKET = {
    platform: { "Solve for": "Coupon (%)", "Issue Price (%)": 100, "Reoffer (%)": 99.5, "Issuer Margin (%)": 1.5 },
    data: {
      Underlying: ["MSFT US"], "Spot Price": [357.12], "Basket Type": "None", Notional: 1000000,
      Tenor: "1Y", Days: 365, Volatility: [0.34], "Skew Beta": [0.1], "Risk-Free Rate": 0.0398,
      "Barrier Type": "European (Maturity)", "KI Barrier (%)": 60, "Put Strike (%)": 100,
      "Leverage (%)": "Yes", "One Star": "No", "One Star Level (%)": 100, "Capital Guaranteed": "No",
      Dividends: [{ underlying_idx: 0, amount: 0, days_to_pay: 20 }],
    },
    coupon_config: { "Coupon Type": "Conditional with Memory", "Coupon Barrier Level (%)": 70, "Coupon Frequency": "Quarterly", "Coupon (%)": "" },
    Autocall: { Type: "Constant Barrier", "Autocall Frequency": "Quarterly", "Autocallable From": "Q1", "Autocall Barrier (%)": 100, "Step Up / Down (%)": 0 },
    Autocall_Coupon: { "Autocall Coupon Type": "None", "AC Coupon (%)": 0 },
    n_sims: 2000,
  };
  var SIMPLE = {
    paths: [null, "n_sims"], n_sims: [null, "n_sims"], greeks: [null, "greeks"],
    solve_for: ["platform", "Solve for"], reoffer: ["platform", "Reoffer (%)"],
    issue_price: ["platform", "Issue Price (%)"], margin: ["platform", "Issuer Margin (%)"],
    notional: ["data", "Notional"], rate: ["data", "Risk-Free Rate"],
    basket: ["data", "Basket Type"], barrier_type: ["data", "Barrier Type"],
    ki_barrier: ["data", "KI Barrier (%)"], put_strike: ["data", "Put Strike (%)"],
    leverage: ["data", "Leverage (%)"], one_star: ["data", "One Star"],
    coupon: ["coupon_config", "Coupon (%)"], coupon_type: ["coupon_config", "Coupon Type"],
    coupon_freq: ["coupon_config", "Coupon Frequency"], coupon_barrier: ["coupon_config", "Coupon Barrier Level (%)"],
    autocall_type: ["Autocall", "Type"], autocall_barrier: ["Autocall", "Autocall Barrier (%)"],
    autocall_freq: ["Autocall", "Autocall Frequency"], autocall_from: ["Autocall", "Autocallable From"],
    ac_coupon: ["Autocall_Coupon", "AC Coupon (%)"], ac_coupon_type: ["Autocall_Coupon", "Autocall Coupon Type"],
  };
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function asList(v) { return Array.isArray(v) ? v : [v]; }

  function buildConfig(params) {
    params = params || {};
    var base, rest;
    if (params.config && typeof params.config === "object") { base = clone(params.config); rest = params; }
    else if (params.platform && params.data) { base = clone(params); rest = {}; }
    else { base = clone(DEFAULT_TICKET); rest = params; }
    ["platform", "data", "coupon_config", "Autocall", "Autocall_Coupon"].forEach(function (k) {
      if (!base[k]) base[k] = clone(DEFAULT_TICKET[k]);
    });
    var tickers = rest.tickers || rest.underlyings || rest.underlying;
    if (tickers) {
      tickers = asList(tickers); var nU = tickers.length;
      base.data.Underlying = tickers;
      base.data["Spot Price"] = asList(rest.spots || rest.spot || Array(nU).fill(100)).slice(0, nU);
      base.data.Volatility = asList(rest.vols || rest.vol || Array(nU).fill(0.3)).slice(0, nU);
      base.data["Skew Beta"] = asList(rest.skews || rest.skew || Array(nU).fill(0.1)).slice(0, nU);
      base.data.Dividends = tickers.map(function (_, i) { return { underlying_idx: i, amount: 0, days_to_pay: 180 }; });
      if (nU > 1 && (base.data["Basket Type"] || "None") === "None") base.data["Basket Type"] = "Worst-Of";
    }
    var days = rest.tenor_days || rest.days;
    if (days != null) {
      base.data.Days = parseInt(days, 10);
      base.data.Tenor = ({ 182: "6M", 365: "1Y", 547: "18M", 730: "2Y" })[base.data.Days] || (base.data.Days + "D");
    }
    Object.keys(SIMPLE).forEach(function (f) {
      if (rest[f] != null) { var s = SIMPLE[f]; if (s[0] === null) base[s[1]] = rest[f]; else base[s[0]][s[1]] = rest[f]; }
    });
    base.n_sims = parseInt(base.n_sims || QuantSuite.DEFAULT_PATHS, 10);
    if (base.greeks == null) base.greeks = 1;   // include the risk block by default
    return base;
  }

  // ---- pricing ---- //
  QuantSuite.price = function (params) {
    return ensureInit().then(function () {
      var cfg = buildConfig(params);
      return global.AmberWASM.runAmberPricing(cfg);   // synchronous CPU work, wrapped in the promise
    });
  };

  QuantSuite.priceWithUI = function (params, ui) {
    ui = ui || {};
    var setStatus = function (m) { if (ui.status) ui.status.textContent = m; };
    var show = function (el, on) { if (el) el.style.display = on ? "" : "none"; };
    if (ui.button) ui.button.disabled = true;
    show(ui.spinner, true);
    setStatus(global.AmberWASM && global.AmberWASM.isReady() ? "Pricing…" : "Loading Amber WASM engine…");
    return QuantSuite.price(params)
      .then(function (res) {
        setStatus("Priced in " + res.ms + " ms via Amber WASM");
        if (typeof ui.onResult === "function") ui.onResult(res);
        return res;
      })
      .catch(function (err) {
        setStatus("Error: " + (err && err.message ? err.message : String(err)));
        if (typeof ui.onError === "function") ui.onError(err);
        throw err;
      })
      .finally(function () { if (ui.button) ui.button.disabled = false; show(ui.spinner, false); });
  };

  // begin loading the engine immediately if the loader is already present
  if (global.AmberWASM) { try { ensureInit(); } catch (e) {} }

  global.QuantSuite = QuantSuite;
  if (typeof module !== "undefined" && module.exports) module.exports = QuantSuite;

})(typeof window !== "undefined" ? window : this);
