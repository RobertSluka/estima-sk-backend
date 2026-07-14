# CLAUDE.md — estima-sk-backend

## What this repo is

Slovak real-estate data/ML pipeline: ingestion of Apify-scraped listings,
historical tracking, market aggregation, feature generation, XGBoost model
registry/training, predictions, and property valuation. PostgreSQL is the
permanent source of truth (Apify datasets are ephemeral). Prices are in **EUR**;
geography is **Slovak kraje/okresy**.

Cloned from `estima-backend` (the CZ/Prague pipeline) and kept **deliberately
separate** — own repo, DB (`estima_sk`), Docker project (`estima-sk`), volumes,
and host ports (Postgres :5433, read API :8011) so it coexists with the live CZ
stack (`backend_startup`, :5432/:8000) and the estima-dev stack (:55432/:8001).

Not responsible for: scraping actors themselves (run via Apify cloud), image
scoring (`estima-vision`), the UI (`estima-sk` frontend), or the standalone
report microservice (`estima-report-service`).

## SK-adaptation status (porting from CZ)

This is a work-in-progress port. What is done vs. inherited-CZ-and-TODO:

- **Done (Phase 0):** repo scaffold, EUR config, SK DB/ports/volumes, booting
  `db` + `read-api` (`/health` green, `/listings` empty), fresh `estima_sk`
  schema auto-creates (12 tables). `sql/init.sql` is source-agnostic and used
  as-is.
- **TODO — still CZ, do not trust as Slovak yet:**
  - `src/services/normalizer.py` — parses Sreality/Bezrealitky JSON; needs a
    Slovak-portal parser (Phase 1).
  - `src/services/prague_districts.py`, `location_scoring.py`,
    `market_statistics.py` — Prague geography/benchmarks; need Slovak
    kraje/okresy (Phase 3).
  - `apify_runner/` + `src/main.py scrape` + `config.APIFY_*_ACTOR_ID` — CZ
    actors; need Slovak-portal actors (Phase 2).
  - No Slovak data exists yet — pipeline is bootstrapped on a seed dataset.

## Architecture

Data flow: `apify_runner/` scrape → `ingestion_runs` → append-only
`raw_listings` (verbatim `raw_json`) → `properties` (canonical, keyed
`(source, source_listing_id)`) → `property_snapshots` (one row per property per
day — core ML asset) → `price_changes` + `market_statistics` →
`property_features` → `ml_dataset_exports` → `model_versions` (artifacts on
disk, never in Postgres) → `predictions`. Sale and rent are never mixed in
aggregates.

- `src/main.py` — Click CLI (migrate, ingest, generate-features, train, …)
- `src/read_api.py` — read-only FastAPI the frontend consumes
  (`/health`, `/listings`, `/raw-listings`, `/benchmarks*`, `/market-index*`,
  `/price-drops`, `/predict`)
- `src/repositories/` — thin per-table SQL; functions take a cursor so callers
  compose one transaction
- `src/services/` — orchestration: `normalizer.py` (raw item → canonical dict),
  `ingestion.py`, `market_statistics.py`, `feature_generation.py`
  (leakage-free), `training.py`, `model_registry.py`, `prediction.py`,
  `vision_scoring.py`, `reports/`
- `sql/init.sql` — full schema for a fresh DB (auto-applied on first volume boot);
  `sql/migrations/*.sql` — ordered, idempotent upgrades tracked in
  `schema_migrations`
- `apify_runner/` — standalone scraper runner (own README)
- `tests/` — normalizer tests are pure; DB tests use a cursor fixture that is
  always rolled back and auto-skip when Postgres is unreachable
- `data/`, `artifacts/` — outputs, git-ignored (not cloned from CZ)

## Commands

Docker Compose project is `estima-sk` (set via `name:` in the compose file, so
no `-p` flag needed). `ml-api` is a profile-gated tools container.

```bash
docker compose up -d db            # start Postgres (schema auto-creates on fresh volume)
docker compose up -d               # also starts read-api on :8011

docker compose run --rm ml-api python -m src.main migrate     # apply SQL migrations
docker compose run --rm ml-api python -m src.main check-db

docker compose run --rm ml-api python -m src.main ingest /app/data/<f>.json --source <sk-source>
docker compose run --rm ml-api python -m src.main generate-features --name base --version v1 --target sale_price
docker compose run --rm ml-api python -m src.main train --feature-set <id>

docker compose run --rm ml-api pytest                         # tests
docker compose run --rm --service-ports ml-api uvicorn src.read_api:app --host 0.0.0.0 --port 8000

docker compose exec db pg_dump -U estima_sk estima_sk > backup_$(date +%F).sql
```

- Install (host, optional): `pip install -r requirements.txt` — pinned versions;
  WeasyPrint needs native libs (`brew install pango` on macOS); Docker is the easy path.
- Lint/format: TODO — no linter config in the repo. CI/CD: none.

## Coding conventions

- Python, pinned deps (`pkg==x.y.z`), Pydantic v2, psycopg2 with
  `RealDictCursor`; SQL lives in `src/repositories/`, logic in `src/services/`.
- Config via `src/config.py` / env (`.env.example` documents variables).
- pytest with `db` marker for DB tests; fixtures roll back, never persist.
- Report wording: estimates only, never claims of exact value.
- `weasyprint==65.1` pairs with `pydyf==0.12.1` — never change one pin without the
  other (mismatch crashes PDF rendering; estima-report-service pins 62.3/0.10.0).

## Do NOT without asking

- Run destructive DB commands (`docker compose down -v` deletes all data;
  no `DROP`/`TRUNCATE`/bulk `DELETE` on live tables). `raw_listings` is
  append-only — never rewrite history.
- Delete or edit existing files in `sql/migrations/` — add new ordered,
  idempotent scripts instead.
- Modify production config or secrets (`.env`, `apify_runner/.env`, tokens).
- Change the read API contract (paths/response shapes) — the frontend consumes it.
- Add/upgrade/unpin dependencies in `requirements.txt`.
- Mix sale and rent data in any aggregate or feature set.
- Touch the CZ sibling repos (`estima-backend`, `estima-frontend`, etc.) while
  working here.
- `git push` unless explicitly asked (origin: github.com/RobertSluka/estima-sk-backend, private).

## Required workflow

1. **Inspect** relevant files (`src/`, `sql/`, `tests/`, README) before changing anything.
2. **Plan** — restate the task as acceptance criteria; milestone plan for multi-file work.
3. **Implement** the smallest change; don't touch unrelated files.
4. **Verify** with `docker compose run --rm ml-api pytest` (DB tests need the
   `db` service up; they skip otherwise).
5. **Summarize** changed files, verification results, and remaining TODOs.

## Project-specific notes

- Postgres data lives in named volume `estima_sk_postgres`; `sql/init.sql` runs
  only on an empty volume — existing data is never touched.
- Features are leakage-free: the target lives in its own column, never in `features_json`.
- The valuation estimate is comparables/median-based; the XGBoost predictor is a
  marked hook, wired in once SK data volume allows.
