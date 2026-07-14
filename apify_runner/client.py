"""
Minimal, dependency-free Apify API client (standard library only).

Starts an Actor run, polls until it finishes, and downloads the full dataset.
Stateless — all run state lives in Apify, so this is safe to re-run any time.

Uses only urllib so the runner works on a clean machine with no `pip install`.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


class ApifyClient:
    def __init__(
        self,
        token: str,
        timeout_seconds: int = 900,
        poll_interval_seconds: int = 15,
    ):
        if not token:
            raise ApifyError("APIFY_API_TOKEN is empty — set it in apify_runner/.env")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    # ── Public API ──────────────────────────────────────────────────────────

    def run_actor(self, actor_id: str, run_input: dict) -> tuple[list[dict], dict]:
        """Start an actor, wait for it, return (items, run_meta)."""
        actor_path = actor_id.replace("/", "~")
        return self._run(f"{APIFY_BASE}/acts/{actor_path}/runs", run_input, actor_id)

    def run_task(self, task_id: str, run_input: dict | None = None) -> tuple[list[dict], dict]:
        """
        Start a saved task, wait for it, return (items, run_meta).

        `run_input` (if given) overrides the task's saved input for this run,
        so the input stays visible and editable in actors.py.
        """
        task_path = task_id.replace("/", "~")
        return self._run(f"{APIFY_BASE}/actor-tasks/{task_path}/runs", run_input, task_id)

    def _run(self, runs_url: str, run_input: dict | None, label: str) -> tuple[list[dict], dict]:
        run_id, dataset_id = self._start_run(runs_url, run_input)
        logger.info("Run started: %s run_id=%s", label, run_id)

        self._wait_for_run(run_id)
        items = self._download_dataset(dataset_id)

        logger.info("Run finished: %d items downloaded", len(items))
        return items, {"run_id": run_id, "dataset_id": dataset_id}

    # ── Internals ───────────────────────────────────────────────────────────

    def _request(self, method: str, url: str, body: dict | None = None,
                 timeout: int = 60) -> dict | list:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ApifyError(f"HTTP {exc.code} on {method} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApifyError(f"Network error on {method} {url}: {exc.reason}") from exc

    def _start_run(self, runs_url: str, run_input: dict | None) -> tuple[str, str]:
        # Apify accepts both "user/name" and "user~name"; the API path needs "~".
        data = self._request(
            "POST", runs_url, body=run_input if run_input is not None else {}, timeout=30
        )["data"]
        return data["id"], data["defaultDatasetId"]

    def _wait_for_run(self, run_id: str) -> None:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            status = self._request(
                "GET", f"{APIFY_BASE}/actor-runs/{run_id}", timeout=15
            )["data"]["status"]

            if status == "SUCCEEDED":
                return
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise ApifyError(f"Run {run_id} ended with status: {status}")

            logger.info("  run %s status: %s — waiting %ds…",
                        run_id, status, self.poll_interval_seconds)
            time.sleep(self.poll_interval_seconds)

        raise ApifyError(f"Run {run_id} timed out after {self.timeout_seconds}s")

    def _download_dataset(self, dataset_id: str) -> list[dict]:
        items: list[dict] = []
        offset, limit = 0, 1000
        while True:
            qs = urllib.parse.urlencode(
                {"format": "json", "offset": offset, "limit": limit, "clean": "true"}
            )
            batch = self._request(
                "GET", f"{APIFY_BASE}/datasets/{dataset_id}/items?{qs}", timeout=120
            )
            if not batch:
                break
            items.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return items
