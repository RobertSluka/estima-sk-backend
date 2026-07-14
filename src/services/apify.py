"""
Apify fetch layer for the src/ pipeline.

This is the missing automation step: trigger an Apify actor (or read an existing
dataset), download its items, and return them along with the run metadata that
`ingestion.ingest_items` records on the ingestion_runs row.

Stateless and idempotent — all run state lives in Apify.
"""

import logging
import time
from typing import Any

import requests

from src import config

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


def _session(token: str | None = None) -> requests.Session:
    tok = token or config.APIFY_API_TOKEN
    if not tok:
        raise ApifyError("APIFY_API_TOKEN is not set")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def run_actor(actor_id: str, run_input: dict[str, Any], *, token: str | None = None) -> dict:
    """
    Start an actor, wait for completion, and return:
      {"items": [...], "meta": {actor_id, run_id, dataset_id, task_id}}.

    Raises ApifyError on timeout or actor failure.
    """
    sess = _session(token)

    resp = sess.post(f"{APIFY_BASE}/acts/{actor_id}/runs", json=run_input, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]
    run_id, dataset_id = data["id"], data["defaultDatasetId"]
    logger.info("Apify run started: actor=%s run_id=%s", actor_id, run_id)

    _wait_for_run(sess, run_id)
    items = _download_dataset(sess, dataset_id)
    logger.info("Apify run %s finished: %d items", run_id, len(items))

    return {
        "items": items,
        "meta": {"actor_id": actor_id, "run_id": run_id, "dataset_id": dataset_id, "task_id": None},
    }


def fetch_dataset(dataset_id: str, *, token: str | None = None) -> dict:
    """
    Read an already-produced dataset (e.g. from an Apify-side scheduled run)
    without triggering a new actor run. Same return shape as run_actor.
    """
    sess = _session(token)
    items = _download_dataset(sess, dataset_id)
    logger.info("Fetched %d items from dataset %s", len(items), dataset_id)
    return {
        "items": items,
        "meta": {"actor_id": None, "run_id": None, "dataset_id": dataset_id, "task_id": None},
    }


# ── Internal ──────────────────────────────────────────────────────────────────


def _wait_for_run(sess: requests.Session, run_id: str) -> None:
    deadline = time.time() + config.APIFY_TIMEOUT_SECONDS
    while time.time() < deadline:
        resp = sess.get(f"{APIFY_BASE}/actor-runs/{run_id}", timeout=15)
        resp.raise_for_status()
        status = resp.json()["data"]["status"]
        if status == "SUCCEEDED":
            return
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise ApifyError(f"Apify run {run_id} ended with status: {status}")
        logger.debug("Apify run %s status: %s — waiting…", run_id, status)
        time.sleep(config.APIFY_POLL_INTERVAL_SECONDS)
    raise ApifyError(f"Apify run {run_id} timed out after {config.APIFY_TIMEOUT_SECONDS}s")


def _download_dataset(sess: requests.Session, dataset_id: str) -> list[dict]:
    items: list[dict] = []
    offset, limit = 0, 1000
    while True:
        resp = sess.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"format": "json", "offset": offset, "limit": limit, "clean": "true"},
            timeout=60,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        items.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return items
