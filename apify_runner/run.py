"""
Run Apify actors and save their datasets to disk.

Usage (from the Backend_startup folder):

    python -m apify_runner.run                 # run every enabled actor once
    python -m apify_runner.run --actor sreality   # run just one actor
    python -m apify_runner.run --list          # list configured actors
    python -m apify_runner.run --daily 06:00   # run now, then every day at 06:00

Configuration:
    1. Copy apify_runner/.env.example to apify_runner/.env
    2. Put your token in it:  APIFY_API_TOKEN=apify_api_xxx
    3. Edit apify_runner/actors.py to choose which actors run.

Output:
    One JSON file per actor per run, written to ./data/ :
        data/<actor-name>_<YYYY-MM-DD_HH-MM-SS>.json

No third-party packages required — standard library only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from apify_runner.actors import ACTORS, Actor
from apify_runner.client import ApifyClient, ApifyError

logger = logging.getLogger("apify_runner")

ROOT = Path(__file__).resolve().parent.parent          # Backend_startup/
DEFAULT_OUTPUT_DIR = ROOT / "data"


# ── Config loading ──────────────────────────────────────────────────────────


def load_env() -> None:
    """Load apify_runner/.env into os.environ (only keys not already set)."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_token() -> str:
    token = os.environ.get("APIFY_API_TOKEN", "").strip()
    if not token:
        sys.exit(
            "ERROR: APIFY_API_TOKEN is not set.\n"
            "  Copy apify_runner/.env.example to apify_runner/.env and add your token,\n"
            "  or run with:  APIFY_API_TOKEN=apify_api_xxx python -m apify_runner.run"
        )
    return token


# ── Running ───────────────────────────────────────────────────────────────────


def save_dataset(actor: Actor, items: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = output_dir / f"{actor.name}_{stamp}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    return path


def _ingest_args(actor: Actor, meta: dict) -> str:
    """CLI flags appended to the ingest command: source + Apify provenance."""
    parts = []
    if actor.source:
        parts.append(f"--source {actor.source}")
    if actor.kind == "task":
        parts.append(f"--apify-task-id {actor.actor_id}")
    else:
        parts.append(f"--apify-actor-id {actor.actor_id}")
    if meta.get("run_id"):
        parts.append(f"--apify-run-id {meta['run_id']}")
    if meta.get("dataset_id"):
        parts.append(f"--apify-dataset-id {meta['dataset_id']}")
    return (" " + " ".join(parts)) if parts else ""


def ingest_file(path: Path, actor: Actor, meta: dict) -> None:
    """
    Load a saved dataset into Postgres via the src/ pipeline.

    By default this runs the ingest inside the ml-api container (which has the
    DB deps and DATABASE_URL configured); the file is reached at /app/<path>
    because docker-compose mounts the repo into the container. Override the base
    command with APIFY_INGEST_CMD ({file} is the repo-relative path; {args} is
    where source/apify flags go), e.g. on a server with a local venv:
        APIFY_INGEST_CMD="python -m src.main ingest {file}{args}"
    """
    rel = path.relative_to(ROOT)
    args = _ingest_args(actor, meta)
    template = os.environ.get(
        "APIFY_INGEST_CMD",
        "docker compose run --rm ml-api python -m src.main ingest /app/{file}{args}",
    )
    if "{args}" in template:
        cmd = template.format(file=rel, args=args)
    else:
        cmd = template.format(file=rel) + args
    logger.info("  ingesting → %s", cmd)
    subprocess.run(cmd, shell=True, check=True, cwd=ROOT)


def run_once(client: ApifyClient, actors: list[Actor], output_dir: Path,
             ingest: bool = False) -> None:
    logger.info("=== Apify run started: %s ===", datetime.now().isoformat(timespec="seconds"))
    saved, failed = 0, 0

    for actor in actors:
        if not actor.enabled:
            logger.info("Skipping %s (disabled)", actor.name)
            continue
        logger.info("Running %s (%s %s)…", actor.name, actor.kind, actor.actor_id)
        try:
            if actor.kind == "task":
                items, meta = client.run_task(actor.actor_id, actor.input)
            else:
                items, meta = client.run_actor(actor.actor_id, actor.input)
            path = save_dataset(actor, items, output_dir)
            logger.info("  saved %d items → %s", len(items), path.relative_to(ROOT))
            saved += 1
            if ingest:
                ingest_file(path, actor, meta)
        except ApifyError as exc:
            logger.error("  FAILED (scrape): %s", exc)
            failed += 1
        except subprocess.CalledProcessError as exc:
            logger.error("  FAILED (ingest): exit %s — JSON was saved, retry ingest manually", exc.returncode)
            failed += 1

    logger.info("=== Done — %d saved, %d failed ===", saved, failed)


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except ValueError:
        raise argparse.ArgumentTypeError("time must be HH:MM, e.g. 06:00")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Apify actors and save datasets locally.")
    parser.add_argument("--actor", help="Run only this actor (by name from actors.py)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--daily", type=parse_hhmm, metavar="HH:MM",
                        help="Run now, then repeat every day at this local time")
    parser.add_argument("--list", action="store_true", help="List configured actors and exit")
    parser.add_argument("--ingest", action="store_true",
                        help="After saving each dataset, load it into Postgres via src/")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    if args.list:
        for a in ACTORS:
            flag = "[on] " if a.enabled else "[off]"
            print(f"{flag} {a.name:<14} {a.kind:<5} {a.actor_id}")
        return

    actors = ACTORS
    if args.actor:
        actors = [a for a in ACTORS if a.name == args.actor]
        if not actors:
            sys.exit(f"No actor named '{args.actor}'. Known: {[a.name for a in ACTORS]}")

    load_env()
    client = ApifyClient(
        token=get_token(),
        timeout_seconds=int(os.environ.get("APIFY_TIMEOUT_SECONDS", "900")),
        poll_interval_seconds=int(os.environ.get("APIFY_POLL_INTERVAL_SECONDS", "15")),
    )

    if not args.daily:
        run_once(client, actors, args.out, ingest=args.ingest)
        return

    hour, minute = args.daily
    logger.info("Daily mode: running now, then every day at %02d:%02d", hour, minute)
    while True:
        run_once(client, actors, args.out, ingest=args.ingest)
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        sleep_s = (nxt - now).total_seconds()
        logger.info("Next run at %s (sleeping %.0f min)", nxt.isoformat(timespec="minutes"), sleep_s / 60)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
