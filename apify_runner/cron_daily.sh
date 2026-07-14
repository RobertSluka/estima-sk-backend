#!/usr/bin/env bash
#
# Daily scrape + ingest, intended to be run from cron.
#
# Cron runs with a minimal environment, so this script:
#   - sets a sane PATH (so `docker` and `python3` are found)
#   - cd's to the repo root (derived from its own location, so it works on any
#     server regardless of where the repo was cloned)
#   - makes sure the Postgres container is up
#   - runs every enabled actor and ingests the results into Postgres
#
# Install (once, on the server):
#   chmod +x apify_runner/cron_daily.sh
#   crontab -e
# then add (runs every day at 06:00, logs to apify_runner/cron.log):
#   0 6 * * * /ABSOLUTE/PATH/TO/Backend_startup/apify_runner/cron_daily.sh >> /ABSOLUTE/PATH/TO/Backend_startup/apify_runner/cron.log 2>&1

set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$PATH"

# Repo root = parent of this script's directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily scrape starting (repo: $REPO_ROOT) ====="

# Ensure the database is running before we try to ingest.
docker compose up -d db

# Scrape every enabled actor and load each result into Postgres.
python3 -m apify_runner.run --ingest

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily scrape done ====="
