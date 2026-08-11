# Deploying QuantSuite — Render backend + GitHub Pages frontend

Two pieces, one repo:

* **Backend** (`server.py`, `Dockerfile`, `render.yaml`, `requirements.txt`) →
  Render.com. Builds the native **Amber** (ngn/k) interpreter and serves
  `POST /api/price`.
* **Frontend** (`index.html`, `app.js`) → GitHub Pages
  (`https://valeriaenglaro.github.io`). Calls the Render API cross-origin.

Both live in `https://github.com/valeriaenglaro/QuantSuite`, so one `git push`
updates both.

---

## 1. Push the changes (triggers Render auto-deploy)

```bash
# from the repo root, on the branch Render tracks (usually main)
git checkout main

git add server.py Dockerfile render.yaml requirements.txt .dockerignore \
        app.js index.html DEPLOY_RENDER.md

git commit -m "Add Render backend: /api/price on native Amber, Docker, CORS, frontend client"

git push origin main
```

That's the whole deploy loop after first-time setup: **push → Render rebuilds
the Docker image → live**. `render.yaml` has `autoDeployTrigger: commit`.

## 2. One-time Render setup (first deploy only)

1. Sign in at <https://dashboard.render.com> with the GitHub account that owns
   the repo.
2. **New → Blueprint** → pick `valeriaenglaro/QuantSuite`. Render detects
   `render.yaml` and proposes the `quantsuite-api` web service (Docker, free).
3. **Apply** → first build runs (Ubuntu + gcc build of Amber + pip install;
   ~3–5 min). When it goes green the service is live at:

   ```
   https://quantsuite-api.onrender.com
   ```

   If Render assigns a different hostname, update `BASE_URL` in `app.js` and the
   Render URL in `index.html` (the `SRV_BASE` line), then push again.
4. Smoke-test:

   ```bash
   curl https://quantsuite-api.onrender.com/health
   curl -X POST https://quantsuite-api.onrender.com/api/price \
        -H 'Content-Type: application/json' \
        -d '{"tickers":["MSFT US"],"spots":[357.12],"vols":[0.34],
             "coupon":0,"ki_barrier":60,"paths":10000,
             "solve_for":"Coupon (%)","engine":"amber"}'
   ```

## 3. One-time GitHub Pages setup (first time only)

Repo **Settings → Pages → Source**: “Deploy from a branch”, branch `main`,
folder `/ (root)` — Pages then serves `index.html` at
`https://valeriaenglaro.github.io/QuantSuite/` (or the user root if this is the
`valeriaenglaro.github.io` repo). `index.html` auto-points at the Render backend
when it detects it is running on `*.github.io`.

To load the API client explicitly, add before `</body>` in `index.html`:

```html
<script src="app.js"></script>
```

---

## `/api/price` contract

**Request** — either flat convenience fields or a full config
(`{platform,data,coupon_config,Autocall,Autocall_Coupon}`):

| field | meaning | example |
|-------|---------|---------|
| `paths` / `n_sims` | Monte-Carlo paths | `10000` |
| `tickers` | underlyings | `["MSFT US","NVDA US"]` |
| `spots`,`vols`,`skews` | per-underlying vectors | `[357.12,120]` |
| `basket` | `None`/`Worst-Of`/`Equally Weighted` | `"Worst-Of"` |
| `barrier_type` | KI observation | `"European (Maturity)"` |
| `ki_barrier`,`put_strike` | % | `60`, `100` |
| `coupon`,`coupon_type`,`coupon_freq`,`coupon_barrier` | coupon leg | `8.0` |
| `autocall_type`,`autocall_barrier`,`autocall_freq`,`autocall_from` | autocall | `"Constant Barrier"` |
| `ac_coupon`,`ac_coupon_type` | autocall coupon | `8.0`,`"Snowball"` |
| `solve_for` | solve target | `"Coupon (%)"`,`"Reoffer (%)"` |
| `rate`,`notional`,`tenor_days` | | `0.0398`,`1000000`,`365` |
| `greeks` | 0 risk-only · 1 +basket · 2 +per-asset | `1` |
| `engine` | `amber` (native) or `python` (fallback) | `"amber"` |

**Response**: `{ PV, Solved, solvable, legs{bond,coupon,autocall_coupon,put},
risk{…}, dist{…}, greeks{…}, acdist{…}, engine, ms }`.

## Notes / decisions

* **Build flag:** the Dockerfile compiles Amber with `-std=gnu11` (not the
  literal `-std=c99` from the brief). The Amber sources use GNU C extensions
  (statement-expressions, named variadic macros) and `PTHREAD_MUTEX_RECURSIVE`,
  which strict C99 rejects; `gnu11` is the minimal change that builds cleanly.
* **K script:** the endpoint runs `master.k` (the parity-verified pricer), not a
  file literally named `pricing.k`.
* **CORS** is scoped to `valeriaenglaro.github.io` + localhost. Set the env var
  `ALLOW_ALL_ORIGINS=1` on the Render service to open it to any origin.
* **Cold start:** the free plan sleeps after ~15 min idle; the first call takes
  ~30–60 s. `app.js` pings `/health` to wake it and shows a status hint.
* **Fallback:** if the native binary is ever missing, `/api/price?…engine=python`
  (or any request when Amber is unavailable) is served by `engine.py`.
