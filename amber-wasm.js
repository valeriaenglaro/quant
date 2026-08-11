/* ==========================================================================
 * amber-wasm.js — load the Amber (ngn/k) interpreter compiled to WebAssembly
 * and price QuantSuite tickets 100% client-side (no server, no network calls
 * after the initial static asset load).
 *
 * The wasm module (amber.wasm) exports:
 *     qs_init()   — initialise the interpreter (once)
 *     qs_inbuf()  — pointer to the input program buffer
 *     qs_run()    — evaluate the buffer; output streams via the js_out import
 *     memory, __heap_base
 * and imports env.{js_alloc,js_free,js_out,js_in,js_time,js_exit,js_eval,
 * sin,cos,log,exp}. JS owns the heap (malloc -> js_alloc).
 *
 * Pricing model: master.k reads its ticket from a global `QSIN` (a JSON string)
 * instead of the json.json file; we inject the JSON (escaped, chunked under the
 * interpreter's string-literal limit) and read the JSON it prints back.
 *
 * Public API:
 *     await AmberWASM.init({ wasmUrl, masterUrl })   // idempotent; returns when ready
 *     AmberWASM.ready                                 // Promise<void>
 *     AmberWASM.runAmberPricing(cfg)                  // -> parsed JSON result
 *     AmberWASM.isReady()                             // bool
 * ======================================================================== */
(function (global) {
  "use strict";

  var _inst = null, _mem = null, _U8 = null, _heapPtr = 0, _initMark = 0;
  var _out = [], _freeList = new Map();
  var _masterBody = null, _readyPromise = null;
  var _enc = new TextEncoder(), _dec = new TextDecoder();

  function _sync() { if (!_U8 || _U8.buffer !== _mem.buffer) _U8 = new Uint8Array(_mem.buffer); }
  function _grow(toBytes) {
    var cur = _mem.buffer.byteLength;
    if (toBytes > cur) { _mem.grow(Math.ceil((toBytes - cur) / 65536)); _sync(); }
  }

  function _env() {
    return {
      js_alloc: function (n) {
        n = (Number(n) + 7) & ~7;
        var fl = _freeList.get(n);
        if (fl && fl.length) return fl.pop();
        var p = _heapPtr; _heapPtr += n; _grow(_heapPtr); return p;
      },
      js_free: function (p, n) {
        n = (Number(n) + 7) & ~7;
        var fl = _freeList.get(n); if (!fl) { fl = []; _freeList.set(n, fl); }
        fl.push(Number(p));
      },
      js_out: function (ptr, n) { _sync(); _out.push(_U8.slice(Number(ptr), Number(ptr) + Number(n))); },
      js_in: function () { return 0; },
      js_time: function (secPtr, usecPtr) {
        _sync(); var ms = Date.now(); var dv = new DataView(_mem.buffer);
        dv.setInt32(Number(secPtr), Math.floor(ms / 1000), true);
        dv.setInt32(Number(usecPtr), (ms % 1000) * 1000, true); return 0;
      },
      js_exit: function () { throw new Error("amber: exit() called"); },
      js_eval: function () { return 0; },
      sin: Math.sin, cos: Math.cos, log: Math.log, exp: Math.exp,
    };
  }

  // escape + chunk a JSON string into K string literals under the ~512-char limit
  function _kliterals(jsonText) {
    var esc = jsonText.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    var chunks = [];
    for (var i = 0; i < esc.length; ) {
      var j = Math.min(i + 200, esc.length);
      while (j < esc.length && esc[j - 1] === "\\") j--;   // never split an escape pair
      chunks.push(esc.slice(i, j)); i = j;
    }
    if (!chunks.length) chunks = [""];
    return chunks.map(function (c) { return '"' + c + '"'; }).join(",");
  }

  function _program(cfg) {
    return "QSIN:" + _kliterals(JSON.stringify(cfg)) + ";\n" + _masterBody;
  }

  var AmberWASM = {
    ready: null,
    isReady: function () { return !!_inst; },

    init: function (opts) {
      if (_readyPromise) return _readyPromise;
      opts = opts || {};
      var wasmUrl = opts.wasmUrl || "amber.wasm";
      var masterUrl = opts.masterUrl || "master.k";
      _readyPromise = Promise.all([
        fetch(wasmUrl).then(function (r) { if (!r.ok) throw new Error("fetch " + wasmUrl + " -> " + r.status); return r.arrayBuffer(); }),
        fetch(masterUrl).then(function (r) { if (!r.ok) throw new Error("fetch " + masterUrl + " -> " + r.status); return r.text(); }),
      ]).then(function (arr) {
        var bytes = arr[0], master = arr[1];
        // master.k, but reading its ticket from the injected QSIN global:
        _masterBody = master.replace('`j?1:"json.json"', "`j?QSIN");
        return WebAssembly.instantiate(bytes, { env: _env() });
      }).then(function (res) {
        _inst = res.instance;
        _mem = _inst.exports.memory; _sync();
        _heapPtr = (_inst.exports.__heap_base.value + 7) & ~7;
        _inst.exports.qs_init();
        _initMark = _heapPtr;   // reset point: reclaims per-run allocations, keeps interp state
      });
      AmberWASM.ready = _readyPromise;
      return _readyPromise;
    },

    // Run master.k on `cfg` and return the parsed JSON result object.
    runAmberPricing: function (cfg) {
      if (!_inst) throw new Error("AmberWASM not initialised — call AmberWASM.init() first");
      _heapPtr = _initMark; _freeList.clear(); _out = [];
      var prog = _enc.encode(_program(cfg));
      var buf = _inst.exports.qs_inbuf();
      _sync();
      _U8.set(prog, buf); _U8[buf + prog.length] = 0;  // NUL-terminate
      var t0 = (global.performance && performance.now) ? performance.now() : Date.now();
      _inst.exports.qs_run();
      var t1 = (global.performance && performance.now) ? performance.now() : Date.now();
      // concatenate js_out chunks
      var total = 0, k; for (k = 0; k < _out.length; k++) total += _out[k].length;
      var all = new Uint8Array(total), off = 0;
      for (k = 0; k < _out.length; k++) { all.set(_out[k], off); off += _out[k].length; }
      var txt = _dec.decode(all).trim();
      if (!txt) throw new Error("Amber produced no output (check parameters)");
      var r = txt.charAt(0) === '"' ? JSON.parse(JSON.parse(txt)) : JSON.parse(txt);
      r.ms = Math.round((t1 - t0) * 100) / 100;
      r.engine = "amber-wasm";
      return r;
    },
  };

  global.AmberWASM = AmberWASM;
  if (typeof module !== "undefined" && module.exports) module.exports = AmberWASM;

})(typeof window !== "undefined" ? window : this);
