"""ml_dataset_exports repository — lineage for exported training CSVs."""


def insert(
    cur,
    *,
    feature_set_id: int,
    export_path: str,
    target: str,
    row_count: int | None = None,
    notes: str | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO ml_dataset_exports
            (feature_set_id, export_path, row_count, target, notes)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (feature_set_id, export_path, row_count, target, notes),
    )
    return cur.fetchone()["id"]
