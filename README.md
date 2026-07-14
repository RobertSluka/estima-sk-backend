# estima-sk-backend — Slovak Real Estate Intelligence Pipeline

A Data/ML pipeline for tracking **Slovak** property listings over time: ingestion,
historical tracking, market aggregation, feature generation, XGBoost training,
predictions, and valuation. PostgreSQL is the source of truth; prices are in
**EUR** and geography is **Slovak kraje/okresy**.

Cloned from the CZ pipeline (`estima-backend`) and kept fully separate — its own
DB (`estima_sk`), Docker project (`estima-sk`), volumes, and ports (Postgres
**:5433**, read API **:8011**) so it runs alongside the CZ and estima-dev stacks.

> **Status:** work-in-progress SK port. Phase 0 (scaffold + booting read API on an
> empty `estima_sk` DB) is done. Ingestion/normalizer (Phase 1), scraper (Phase 2),
> geography + market stats (Phase 3), and valuation (Phase 4) still inherit CZ code
> and are being adapted. See `CLAUDE.md` → "SK-adaptation status" for the live
> checklist. No Slovak data exists yet; the pipeline is bootstrapped on a seed
> dataset.

## Quick start

```bash
cp .env.example .env          # adjust secrets/ports as needed
docker compose up -d          # db (:5433) + read-api (:8011)

curl http://localhost:8011/health          # {"status":"ok","properties":0}
curl "http://localhost:8011/listings?limit=5"
```

## Layout

- `src/` — pipeline (`main.py` CLI, `read_api.py`, `repositories/`, `services/`)
- `sql/init.sql` + `sql/migrations/` — schema (source-agnostic; auto-applies on a
  fresh volume)
- `apify_runner/` — scraper runner (CZ actors for now; SK actors in Phase 2)
- `tests/` — pytest; DB tests roll back and skip when Postgres is down
- `data/`, `artifacts/` — git-ignored outputs

## Commands

See `CLAUDE.md` for the full command list, conventions, and the SK-adaptation
status. Everything runs through Docker Compose (project `estima-sk`).
