// wasm_smoke.js — CI smoke test: load amber.wasm in Node (browser fetch shimmed)
// and price the sample ticket. No native binary needed. Exits non-zero on failure.
const fs = require("fs");
global.window = global;
global.fetch = (u) => Promise.resolve({
  ok: true, status: 200,
  arrayBuffer: async () => fs.readFileSync(u).buffer,
  text: async () => fs.readFileSync(u, "utf8"),
});
const AmberWASM = require("./amber-wasm.js");

(async () => {
  await AmberWASM.init({ wasmUrl: "amber.wasm", masterUrl: "master.k" });
  const cfg = JSON.parse(fs.readFileSync("json.json", "utf8"));
  cfg.n_sims = 2000; cfg.greeks = 2;
  const r = AmberWASM.runAmberPricing(cfg);
  console.log("PV=%s Solved=%s p_autocall=%s delta=%s ms=%s",
    r.PV, r.Solved, r.risk && r.risk.p_autocall, r.greeks && r.greeks.delta, r.ms);
  const ok = typeof r.PV === "number" && isFinite(r.PV) &&
             typeof r.Solved === "number" && r.risk && typeof r.risk.p_autocall === "number" &&
             r.greeks && typeof r.greeks.delta === "number";
  if (!ok) { console.error("SMOKE FAIL: result shape invalid", JSON.stringify(r).slice(0, 200)); process.exit(1); }
  // vanilla ticket solves the coupon so PV pins to Reoffer-margin = 98
  if (Math.abs(r.PV - 98) > 1) { console.error("SMOKE FAIL: PV expected ~98, got", r.PV); process.exit(1); }
  console.log("WASM smoke OK");
})().catch((e) => { console.error("SMOKE FAIL:", e); process.exit(1); });
