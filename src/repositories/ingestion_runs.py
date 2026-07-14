"""ingestion_runs repository — one row per Apify scrape batch."""

from datetime import datetime


def create(
    cur,
    *,
    source: str,
    status: str = "running",
    started_at: datetime | None = None,
    apify_actor_id: str | None = None,
    apify_task_id: str | None = None,
    apify_run_id: str | None = None,
    apify_dataset_id: str | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO ingestion_runs (
            source, apify_actor_id, apify_task_id, apify_run_id, apify_dataset_id,
            started_at, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (source, apify_actor_id, apify_task_id, apify_run_id, apify_dataset_id,
         started_at, status),
    )
    return cur.fetchone()["id"]


def finish(
    cur,
    run_id: int,
    *,
    status: str,
    finished_at: datetime,
    item_count: int | None = None,
) -> None:
    cur.execute(
        """
        UPDATE ingestion_runs
        SET status = %s, finished_at = %s, item_count = %s
        WHERE id = %s
        """,
        (status, finished_at, item_count, run_id),
    )
