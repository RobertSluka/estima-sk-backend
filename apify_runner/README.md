# Apify Runner

Run Apify actors locally and save their datasets to disk. Self-contained and
dependency-free (Python standard library only) so it's trivial to move to a
server later.

## Setup (one time)

```bash
cp apify_runner/.env.example apify_runner/.env
# then edit apify_runner/.env and paste your token:
#   APIFY_API_TOKEN=apify_api_xxxxxxxx
```

Get your token at https://console.apify.com/settings/integrations.

## Run

From the `Backend_startup` folder:

```bash
python -m apify_runner.run                  # run every enabled actor once
python -m apify_runner.run --actor sreality # run a single actor
python -m apify_runner.run --list           # show configured actors
python -m apify_runner.run --daily 06:00    # run now, then daily at 06:00
```

Output: one JSON file per actor per run, in `./data/`:

```
data/sreality_2026-06-18_06-05-15.json
data/cz-reality_2026-06-18_06-05-20.json
```

## Scrape AND load into Postgres

Add `--ingest` to load each saved dataset into the database right after it's
scraped, using the `src/` pipeline (raw_listings → properties → snapshots →
price_changes):

```bash
python3 -m apify_runner.run --ingest             # all actors, scrape + ingest
python3 -m apify_runner.run --actor cz-reality --ingest
```

Requirements for `--ingest`:
- The Postgres container is up: `docker compose up -d db`
- By default ingest runs inside the `ml-api` container (it has the DB deps and
  `DATABASE_URL`), reaching files via the mounted `./data` → `/app/data`.

If the scrape succeeds but ingest fails, the JSON is already saved — just retry
the ingest manually:

```bash
docker compose run --rm ml-api python -m src.main ingest /app/data/<file>.json
```

To ingest without Docker (e.g. on a server with a local venv), override the
command — `{file}` is the repo-relative path:

```bash
APIFY_INGEST_CMD="python -m src.main ingest {file}" python3 -m apify_runner.run --ingest
```

### Verify what landed

```bash
docker exec backend_startup-db-1 psql -U realestate -d prague_realestate \
  -c "SELECT source, count(*) FROM properties GROUP BY source;"
```

## Add or change actors

Edit `apify_runner/actors.py` — that's the only file you touch. Append an entry:

```python
Actor(
    name="my-scraper",                 # used in the output filename
    actor_id="username/actor-name",    # from the Apify console
    input={"location": "Praha", "maxItems": 5000},
),
```

The `input` dict is passed straight to the actor; valid fields are listed on
the actor's **Input** tab in the Apify console. Set `enabled=False` to skip an
actor without deleting it.

## Moving to a server

The DB schema auto-creates on first boot (docker-compose mounts `sql/init.sql`
into a fresh Postgres volume), so server setup is:

```bash
# 1. clone the repo
git clone <your-repo-url> && cd Backend_startup

# 2. add your token (not in git)
cp apify_runner/.env.example apify_runner/.env   # then paste APIFY_API_TOKEN

# 3. start Postgres (schema is created automatically the first time) + build image
docker compose up -d db
docker compose build ml-api

# 4. one manual run to confirm it works end-to-end
python3 -m apify_runner.run --ingest

# 5. schedule it daily
chmod +x apify_runner/cron_daily.sh
crontab -e
```

Add this cron line (absolute paths required — cron has no working dir):

```cron
0 6 * * * /ABS/PATH/Backend_startup/apify_runner/cron_daily.sh >> /ABS/PATH/Backend_startup/apify_runner/cron.log 2>&1
```

`cron_daily.sh` sets PATH, cd's to the repo, brings up the DB, and runs
`apify_runner.run --ingest` for every enabled actor.

> Only bring up `db` (and use `docker compose run --rm ml-api` for ingest).
> Don't `docker compose up` the whole stack — the `ml-api`/`worker` services
> belong to the older `app/` pipeline and don't match this database.
