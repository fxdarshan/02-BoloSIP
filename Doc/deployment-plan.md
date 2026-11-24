# BoloSIP: deployment plan (Railway)

> **Facts-only. No investment advice.**

| | |
|---|---|
| **Version** | 1.2 (24 Nov 2026) |
| **Goal** | Run BoloSIP as a public website on [Railway](https://railway.com), served from this GitHub repository, with the same answers, privacy and freshness as on the laptop |
| **Status** | **Live** at https://02-bolosip-production.up.railway.app (24 Nov 2026): `scripts/smoke_remote.py` passes **20/20** (health, 27 schemes, embedding search, today's data, answers with source and date, refusals, per-browser chats, foreign-origin block, `Secure` cookie, HSTS). Groq rephrasing on with a new, sealed key (the earlier key was rotated after being pasted in chat). Volume attached at `/data`; `BOLOSIP_DB` and `BOLOSIP_CHROMA_DIR` must point into it. Trial plan, region US East. The first 502s were `BOLOSIP_HOST=127.0.0.1` copied from a laptop `.env` (ISS-052, now overridden in code) |
| **Related** | [Implementation plan](Implementation-plan.md) (Phase 7 daily refresh, Phase 10 release), [architecture](architecture.md) §13 API, §17 security, [issues log](issues.md) |

Railway facts in this plan were checked against docs.railway.com on **23 Nov 2026** (sources in §12). Railway changes often: recheck the items marked ⚠️ before each stage.

---

## 1. Summary of decisions

| Choice | Decision | Why |
|---|---|---|
| Plan | **Hobby** ($5 a month, includes $5 of usage) | The server uses about **680 MB of memory** with the embedding search (measured 23 Nov 2026). The Free plan allows 0.5 GB per service and the Trial plan 1 GB, so both are too small or too tight |
| Services | **One web service**, one replica | SQLite and the in-process search index are single-node by design (arch §20). Railway does not allow replicas on a service with a volume |
| Build | **Dockerfile** in the repo | Pins Python 3.12 (Railpack's default is 3.13.2, and the embedding packages are tested on 3.12), installs `.[embed]`, and puts the 550 MB embedding model **inside the image**, so a restart never downloads it again |
| Storage | **One volume mounted at `/data`** | Keeps the conversations database (`bolosip.sqlite3`) and the local ChromaDB folder across redeploys. The fact data (`corpus.json`, vectors) comes from git, inside the image |
| Retrieval | `BOLOSIP_RETRIEVER=embed` | Same as the laptop: 93% against 69% with keyword search. `embed` stops the deploy if the model is missing, so the site never falls back to the weaker search silently |
| LLM | `BOLOSIP_LLM=off` until Phase 8 is built and accepted | Then `auto`, with `GROQ_API_KEY` set as a sealed Railway variable, never in git |
| Deploys | **Automatic from `main`**, with "Wait for CI" and watch paths | Every code push and every daily data commit deploys by itself. A push that only touches docs does not redeploy |
| Domain | `*.up.railway.app` first; a custom domain later (optional) | TLS certificates are issued and renewed by Railway |
| Settings | Set in the Railway dashboard, recorded in §6 of this file | ⚠️ Railway's `railway.json` / `railway.toml` (config as code) is deprecated: existing files work until **1 Dec 2026** and new services cannot opt in. Its replacement (`.railway/railway.ts`, infrastructure as code) needs TypeScript tooling; adopt it later only if the dashboard settings drift |
| Sleeping | **Off** | A sleeping service answers its first request with a possible 502 and then loads the model; a facts assistant should answer straight away |

## 2. How it fits together

```
 GitHub (fxdarshan/02-BoloSIP, branch main)
   │   push: code change by the owner, or the daily "Data refresh" commit at ~10:00 IST
   ▼
 Railway: waits for GitHub checks → builds the Dockerfile → starts the new container
   │   healthcheck GET /api/health must return 200 within 300 s, else the old one stays live
   ▼
 Railway edge (HTTPS, TLS 1.2/1.3, adds X-Real-IP, X-Forwarded-Proto, X-Forwarded-Host)
   ▼
 Container: python server.py on 0.0.0.0:$PORT
   ├─ image  : code, web/, data/corpus.json, data/embeddings.npy/.json, embedding model
   └─ volume : /data/bolosip.sqlite3 (redacted chats), /data/chroma (rebuilt from the vectors)
```

The daily refresh (Phase 7) needs no extra work on Railway: the refresh workflow runs every test and gate **before** it commits, then the commit to `main` triggers a Railway deploy with the new data. On start-up the server sees new vectors and rebuilds its ChromaDB collection on the volume by itself.

## 3. Blockers: what must change in the code first (stage D0)

The server was built for one person on `127.0.0.1`. These changes are needed before anyone else can reach it. Each one gets tests, and every gate must still pass.

| # | Change | Why it blocks a public deploy | Where |
|---|---|---|---|
| B1 | **Chats belong to one browser.** Give each visitor a random owner id in an `HttpOnly; Secure; SameSite=Strict` cookie; store it (hashed) with each thread; `GET /api/threads`, reading, posting and deleting only work on that owner's threads (404 otherwise) | Today `GET /api/threads` lists **every** conversation on the server. On a public site any visitor would see everyone's chats | `server.py`, `bolosip/store.py` (new `owner` column with a migration), `web/index.html`, `tests/test_api.py`, `tests/test_threads.py` |
| B2 | **Listen where Railway expects.** If `PORT` is set, use it (it wins over `BOLOSIP_PORT`); set `BOLOSIP_HOST=0.0.0.0` | Railway sends traffic and the healthcheck to `$PORT`; the server now binds `127.0.0.1:8000` | `bolosip/config.py`, `server.py` |
| B3 | **Allow the public host name.** New setting `BOLOSIP_PUBLIC_HOSTS` (comma-separated, default from `RAILWAY_PUBLIC_DOMAIN`). Accept those names without a port, and accept `https://<name>` as an `Origin`. Allow `healthcheck.railway.app` as the `Host` for `GET /api/health` only | The Host check (GAP-08) only knows `127.0.0.1`, `localhost` and `[::1]` with the port, and only `http://` origins, so every public request and the healthcheck would get 403 | `server.py`, `tests/test_api.py` (`TestOriginChecks`) |
| B4 | **Rate-limit the real visitor.** With `BOLOSIP_TRUST_PROXY=1`, take the client IP from `X-Real-IP` (set by Railway's edge); never trust it otherwise. ⚠️ In D4, confirm the edge replaces a client-sent `X-Real-IP` (send a fake one 31 times; the 31st message must still get 429) | Behind the proxy every request comes from Railway's address, so the 30-a-minute limit would be shared by all visitors | `server.py`, `tests/test_api.py` (`TestRateLimit`) |
| B5 | **Stop cleanly.** Handle `SIGTERM`: stop accepting requests, finish the ones in flight, close SQLite | Railway sends `SIGTERM` on every redeploy (daily), then kills the container after `drainingSeconds` | `server.py` |
| B6 | **HTTPS headers.** When `X-Forwarded-Proto` is `https`, add `Strict-Transport-Security: max-age=31536000`; keep the current CSP, `nosniff` and no-CORS rules | The site is only served over HTTPS; browsers should never try plain HTTP | `server.py` |
| B7 | **Keep chats for a limited time.** New setting `BOLOSIP_RETENTION_DAYS` (30 on Railway); delete older threads at start-up and once a day | Stored questions are redacted, but a public site should not keep them forever. State the period in the privacy hint | `bolosip/store.py`, `bolosip/config.py`, `server.py` |
| B8 | **Public-bind warning.** Keep the SEC-03 warning, but when `BOLOSIP_TRUST_PROXY=1` and `BOLOSIP_PUBLIC_HOSTS` is set, log one line that says the site is public by design | The current warning would print on every start and hide real warnings | `server.py` |
| B9 | **Settings documented.** Add the new variables to `.env.example` (with their local defaults) and to the README | One place for every setting (Phase 0 rule) | `.env.example`, `README.md` |

Nothing else in the pipeline changes: guards, retrieval, answers and the daily refresh behave exactly as on the laptop.

## 4. Files to add

| File | Contents |
|---|---|
| `Dockerfile` | `FROM python:3.12-slim`; copy `pyproject.toml` and `bolosip/` first and `pip install --no-cache-dir ".[embed]"` (so code-only changes reuse the cached dependency layer); copy the rest; **download the embedding model at build time** into `/app/.cache/models` (`python -c` that loads `nomic-ai/nomic-embed-text-v1.5` through `bolosip.embedder`); run as a non-root user; `CMD ["python", "server.py"]` |
| `scripts/docker-entrypoint.sh` | Creates `/data` and `/data/chroma`, gives them to the `app` user (Railway mounts volumes owned by root), then runs the server as `app` with `setpriv`. No `RAILWAY_RUN_UID` needed |
| `.dockerignore` | `.git`, `.github`, `.venv`, `.cache`, `.claude`, `.env`, `__pycache__`, `*.egg-info`, `graft`, `stitch_bolosip_mutual_fund_assistant`, `Doc`, `tests`, `eval`, `data/raw` (only `ingest.py` reads the saved pages), `data/chroma`, `data/*.sqlite3*` |
| `scripts/smoke_remote.py` | Stdlib-only check of a deployed URL, acting as two browsers: `/api/health` (27 schemes, dense retriever, `data_age_days` ≤ `--max-age`, default 3), the page with its CSP and cookie flags (plus `Secure` and HSTS over HTTPS), one answer with its source and footer, an advice refusal, a personal-data reply, a 403 for a foreign `Origin`, and 404s when the second browser reads or deletes the first one's chat (B1). It deletes its test chat. 18 checks on `http://`, 20 on `https://` |
| `.github/workflows/tests.yml` job `docker` | Builds the image, runs it like Railway (`PORT=7123`, a `/data` volume, `BOLOSIP_TRUST_PROXY=1`, a public host), runs the smoke test, checks the healthcheck Host rule and the non-root user, stops it with SIGTERM (exit code 0, "BoloSIP stopped."), and checks the database and ChromaDB are on the volume after a restart |
| `Doc/deployment-plan.md` | This file |

`.env` is never copied into the image (`.dockerignore`) and never committed. Secrets live only in Railway variables.

## 5. Volume

| Item | Value |
|---|---|
| Mount path | `/data` |
| Size | 1 GB to start (Hobby allows up to 5 GB; a volume can grow but never shrink) |
| Holds | `/data/bolosip.sqlite3` (+ `-wal`, `-shm`), `/data/chroma/` |
| Does not hold | `corpus.json`, the vectors and the model: they come with the image, so a deploy always serves the data of its own commit |
| Backups | ⚠️ Turn on Railway's volume backups (daily, keep 7) after the first deploy; check the backups page, which was not read for this plan |
| Note | A service with a volume has a short gap (seconds) during each redeploy, even with a healthcheck. With the daily data commit this means one short gap around 10:00–10:10 IST. Accepted |

If the database file is ever damaged, deleting it is safe: the server creates an empty one, and only past chats are lost. The facts are never on the volume.

## 6. Service settings (Railway dashboard)

**Build and deploy**

| Setting | Value |
|---|---|
| Source | GitHub repo `fxdarshan/02-BoloSIP`, branch `main` |
| Builder | Dockerfile (`Dockerfile` at the repo root) |
| Start command | none (the Dockerfile `CMD`) |
| Healthcheck path | `/api/health` |
| Healthcheck timeout | 300 s (default). Start-up loads the model and may rebuild ChromaDB; measure it in D3 and keep at least twice that |
| Restart policy | On failure, max 5 retries |
| Draining time | 10 s (lets B5 finish requests in flight) |
| Replicas / region | 1 replica; the region closest to India that Railway offers (⚠️ check the list; Singapore if available) |
| Serverless (app sleeping) | Off |
| Wait for CI | On |
| Watch paths | `bolosip/**`, `web/**`, `server.py`, `ingest.py`, `data/corpus.json`, `data/embeddings.*`, `pyproject.toml`, `Dockerfile`, `.dockerignore` |

**Variables**

| Variable | Value | Notes |
|---|---|---|
| `BOLOSIP_HOST` | `::` (set in the Dockerfile) | B2: listens on IPv6 and IPv4 together, whichever the edge uses |
| `PORT` | **`8000`**, and the domain's target port **8000** | B2. Railway injects its own `PORT` (often 8080) and the app listens there; a domain generated with another target port answers 502 (ISS-048). Set both to the same number. ⚠️ Lesson from D3 |
| `BOLOSIP_PUBLIC_HOSTS` | `${{RAILWAY_PUBLIC_DOMAIN}}` (plus the custom domain later) | B3 |
| `BOLOSIP_TRUST_PROXY` | `1` | B4 |
| `BOLOSIP_RETRIEVER` | `embed` | Never fall back to keyword search silently |
| `BOLOSIP_DB` | `/data/bolosip.sqlite3` | On the volume |
| `BOLOSIP_CHROMA_DIR` | `/data/chroma` | On the volume |
| `BOLOSIP_MODEL_CACHE` | `/app/.cache/models` | Inside the image |
| `BOLOSIP_RETENTION_DAYS` | `30` | B7 |
| `BOLOSIP_RATE_MSG` / `BOLOSIP_RATE_ALL` | `30` / `120` | Per visitor, per minute (same as local) |
| `BOLOSIP_LLM` | `off` | `auto` after Phase 8 |
| `GROQ_API_KEY` | not set until Phase 8; then **sealed** | Never in git, never in logs |
| `BOLOSIP_SKIP_DOTENV` | `1` | There is no `.env` in the container; settings come only from Railway |

## 7. Stages

Each stage ends with its check; do not start the next one until it passes.

| Stage | What happens | Done when |
|---|---|---|
| **D0. Code changes** ✅ | B1–B9 from §3, `Dockerfile`, `.dockerignore`, `scripts/smoke_remote.py`; tests for each (`tests/test_deploy.py`, 16 tests); README "Deploy on Railway" section | Done 23 Nov 2026: 266 tests and every gate pass (keyword and embedding search); the smoke test passes 18/18 on the local server; the `docker` CI job builds and checks the image (Docker is not installed on the laptop, so CI is the image check) |
| **D1. Account and project** | The owner creates the Railway account (the owner signs in and enters payment details; Claude never does), picks Hobby, creates a project from the GitHub repo and gives Railway access to this repository only | The project shows the repo and branch `main` |
| **D2. Settings** | §6 settings and variables, the `/data` volume; generate the `*.up.railway.app` domain | Every row of §6 matches the dashboard |
| **D3. First deploy** | Railway builds and starts; read the build and deploy logs; check the domain's target port equals the port in the log line `BoloSIP … on http://[::]:NNNN` | Healthcheck passes; logs show "retriever: dense (nomic + ChromaDB)" and no warning other than expected ones; start-up time recorded here |
| **D4. Smoke test** | `python scripts/smoke_remote.py https://<domain>` from the laptop; then the manual pass on a phone and a desktop browser (examples, typing suggestions, chips, drawer, dark/light) | Every smoke check passes; the footer date equals the latest data commit; a second browser cannot see the first one's chats |
| **D5. Daily refresh on Railway** | Wait for the next 10:00 IST refresh commit | Railway deploys it by itself; `/api/health` shows `data_age_days` 0 the same morning; the gap during the redeploy is seconds |
| **D6. Monitoring** | Railway's healthcheck only runs at deploy time, so add an outside check: a small step in `refresh-data.yml` that runs `smoke_remote.py` after the data commit has deployed, plus a free uptime monitor on `/api/health` (owner's choice of service) | A stopped service is noticed within an hour; a failed smoke check opens the `data-refresh` issue |
| **D7. Custom domain (optional)** | Add the domain in Railway, then the CNAME and TXT records at the DNS provider; add it to `BOLOSIP_PUBLIC_HOSTS` | HTTPS works on the custom domain; the Railway domain still works |
| **D8. Go public** | Link from the README; note the URL in the problem statement deliverables (PS §9) | Owner sign-off |

Suggested timing: D0 can start now. D1–D5 fit best after Phase 9 (acceptance), so the public site starts with accepted answers; Phase 8 (LLM) can follow with only a variables change and a redeploy.

## 8. Rollback

| Situation | What to do |
|---|---|
| A deploy fails its healthcheck | Nothing: Railway keeps the previous deployment live |
| A deploy is live but wrong (bad answers, errors) | Railway dashboard → Deployments → the last good one → **Redeploy**. Then fix on `main`; the next push deploys normally |
| Bad data committed by the refresh | `git revert` the "Data refresh" commit and push; Railway deploys the reverted data. Investigate with the run's change report |
| Database damaged | Stop the service, delete `/data/bolosip.sqlite3*` (or restore a volume backup), start again |
| Railway itself is down | The laptop still runs everything (`python server.py`); nothing in BoloSIP depends on Railway |

## 9. Cost estimate

Railway bills used memory and CPU by the minute. These figures are an estimate, to be replaced by the real numbers after one week (D5).

| Item | Estimate |
|---|---|
| Hobby subscription | $5 a month, which includes $5 of usage |
| Memory: about 0.7 GB, always on, at $10 per GB-month | about $7 |
| CPU: idle most of the time, short bursts per answer | under $1 at low traffic |
| Volume: 1 GB at $0.15 per GB-month | about $0.15 |
| Egress: small JSON replies, $0.05 per GB | cents |
| **Total** | **about $8 a month** ($5 subscription + about $3 above the included usage) |

Set a usage limit (spending cap) in Railway's workspace settings at $15 a month, so a traffic spike cannot run up a bill.

## 10. Security and privacy on a public server

| Rule (from the problem statement and architecture §17) | How it holds on Railway |
|---|---|
| Personal data is never stored or sent to the LLM | Unchanged: guards and redaction run before anything is saved |
| Nobody sees another person's chats | B1 (owner cookie); tested by `smoke_remote.py` |
| No secrets in git | `.env` excluded by `.gitignore` and `.dockerignore`; the Groq key is a sealed Railway variable |
| Only the 27 Groww pages are fetched | The server never scrapes; fetching happens only in the GitHub refresh workflow |
| Embeddings stay local | The model runs inside the container; no question goes to an embedding API |
| ChromaDB telemetry off | Unchanged (`anonymized_telemetry=False`) |
| Logs never hold message text | Unchanged; Railway's log view shows method, path, status and time only |
| Abuse | Per-visitor rate limits (B4), the 500-character limit, the request body limit and the socket timeout all stay; Railway's edge adds its own per-domain limit |
| Not investment advice | The disclaimer banner and the refusals are unchanged |

## 11. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Railway removes config as code on 1 Dec 2026 | None for this plan | Settings live in the dashboard and in §6; nothing depends on `railway.json` |
| Memory above 1 GB under load | Higher bill, or a restart if a limit is set too low | Measure in D5; the ThreadingHTTPServer shares one model, so memory grows little with visitors |
| Daily redeploy gap around 10:00 IST | A few seconds of errors for anyone mid-question | Accepted; the web page already shows a "try again" message on a failed request |
| Image too large or build too slow | Slow deploys | The dependency layer is cached; only the code and data layers change daily |
| The bot commit has no GitHub checks to wait for | Railway deploys it without waiting | Fine: the refresh workflow ran every test and gate before committing (Phase 7) |
| Volume full | Writes fail ("Could not save message") | Retention (B7) keeps the database small; resize the volume if needed |
| Groww blocks the GitHub runner | Data goes stale on the site | Phase 7 already opens the `data-refresh` issue; `data_age_days` shows on `/api/health` and in D6 |

## 12. Sources (read 23 Nov 2026)

- Config as code (deprecation notice) and infrastructure as code: https://docs.railway.com/reference/config-as-code, https://docs.railway.com/infrastructure-as-code
- Builds and Railpack's Python support (default Python 3.13.2, version pinning): https://docs.railway.com/builds, https://railpack.com/languages/python
- Healthchecks (deploy time only, default 300 s, `PORT`): https://docs.railway.com/guides/healthchecks
- Public networking (headers, TLS, limits, domains): https://docs.railway.com/networking/public-networking/specs-and-limits, https://docs.railway.com/networking/domains
- Volumes (sizes, no replicas, redeploy gap): https://docs.railway.com/reference/volumes
- GitHub autodeploys (Wait for CI, watch paths): https://docs.railway.com/guides/github-autodeploys
- Plans and pricing: https://docs.railway.com/reference/pricing/plans
- App sleeping: https://docs.railway.com/reference/app-sleeping

Not read (check before the stage that needs them): the volume backups page (D2), the region list (D2), and the build timeout (D3).
