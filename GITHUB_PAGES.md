# Hosting QuantSuite output on GitHub Pages

GitHub Pages serves **static files only** — there is no backend process at view
time, so `server.py` / engine.py / the `k` binary cannot run when a visitor
opens the page. There are two ways to put live pricer output on Pages anyway.
This repo ships the first (reliable, already wired up) and documents the second.

---

## Approach A — pre-compute with Amber during the CI build (implemented)

The idea: do the pricing **in GitHub Actions**, where Amber and Python *can*
run, then publish the resulting HTML. Every number is baked in at build time.

Flow (all in `.github/workflows/ci.yml`):

1. `parity` job builds Amber from source on Linux + macOS and gates on
   engine.py ↔ master.k parity. Pages only builds if parity is green.
2. `pages` job builds Amber, then runs **`build_site.py --kbin ./amber_src/amber
   --out ./_site`**. That script runs `master.k` through Amber on a handful of
   sample tickets (and engine.py alongside for the baseline column) and writes a
   single self-contained `_site/index.html`. It is uploaded with
   `actions/upload-pages-artifact`.
3. `deploy-pages` job publishes the artifact with `actions/deploy-pages`.

### One-time repository setup

1. Push this repo to GitHub with `main` as the default branch.
2. **Settings → Pages → Build and deployment → Source: “GitHub Actions”.**
   (Do *not* pick “Deploy from a branch”.)
3. Ensure Actions can deploy Pages: **Settings → Actions → General → Workflow
   permissions** → allow read/write (the workflow also requests `pages: write`
   and `id-token: write` explicitly, which is what Pages needs).
4. Push to `main` (or run the workflow from the Actions tab). After the
   `deploy-pages` job succeeds, the site URL appears in the job summary and at
   **Settings → Pages** — typically
   `https://<user>.github.io/<repo>/`.

### Customising what gets published

* Edit the `tickets()` list in `build_site.py` to price whatever structures you
  want on the page.
* To also publish the interactive terminal `index.html`, copy it into `_site/`
  in the `pages` job — but note its charts price against the local
  `server.py`, so on Pages it renders the UI while the *numbers* come from the
  pre-computed `build_site.py` output, not a live server.

### Running it locally before pushing

```bash
git clone --depth 1 https://github.com/BonucciAndrea/amber.git amber_src
cd amber_src && bash build.sh && cd ..
python3 build_site.py --kbin "$PWD/amber_src/amber" --out ./_site
open ./_site/index.html          # macOS ( xdg-open on Linux )
```

---

## Approach B — compile Amber to WebAssembly (fully interactive, in-browser)

Amber ships a WASM entry point (`amber/src/amber_wasm.c`; this repo also carries
`k_source/wasm-push.sh`). Compiling it with Emscripten produces a `.wasm` +
JS glue that runs the **whole ngn/k interpreter in the visitor's browser**, so
`master.k` can be re-priced client-side from a form — no rebuild, no server.

Build step (add as a job or run locally with the Emscripten SDK on `PATH`):

```bash
git clone --depth 1 https://github.com/BonucciAndrea/amber.git amber_src
cd amber_src
emcc -O3 src/amber_wasm.c -o ../_site/amber.js \
     -s MODULARIZE=1 -s EXPORT_NAME=Amber \
     -s EXPORTED_RUNTIME_METHODS=cwrap,FS \
     -s ALLOW_MEMORY_GROWTH=1
# ship master.k next to it so the page can load & eval it:
cp ../master.k ../_site/master.k
```

Then a small `index.html` loads `amber.js`, writes the user's ticket JSON into
the WASM in-memory FS (`Module.FS.writeFile('json.json', ...)`), evaluates
`master.k`, and renders the returned JSON.

To wire this into CI, add before the Pages upload:

```yaml
      - name: Install Emscripten
        uses: mymindstorm/setup-emsdk@v14
      - name: Compile Amber to WASM
        run: |
          emcc -O3 amber_src/src/amber_wasm.c -o _site/amber.js \
            -s MODULARIZE=1 -s EXPORT_NAME=Amber \
            -s EXPORTED_RUNTIME_METHODS=cwrap,FS -s ALLOW_MEMORY_GROWTH=1
          cp master.k _site/master.k
```

**Trade-offs.** Approach A is deterministic, tiny, and always works — the page
can never diverge from the CI-verified parity because the same Amber binary
produced both. Approach B is interactive (visitors change inputs and re-price
live) but ships a multi-hundred-KB `.wasm`, depends on the Emscripten toolchain
in CI, and exercises the `amber_wasm.c` path rather than the native binary the
parity suite validates. Start with A; add B when you want live inputs.

---

## Which URL / where it lands

| item | location |
|------|----------|
| Published site | `https://<user>.github.io/<repo>/` |
| Pages source setting | Settings → Pages → Source = **GitHub Actions** |
| Build logs | Actions tab → latest `CI` run → `pages` / `deploy-pages` jobs |
| Site generator | `build_site.py` |
| Workflow | `.github/workflows/ci.yml` |
