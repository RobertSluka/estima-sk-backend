"""model_versions repository — trained model registry (artifact paths only)."""

from datetime import datetime

from psycopg2.extras import Json


def insert(
    cur,
    *,
    model_name: str,
    version: str,
    target: str,
    framework: str,
    artifact_path: str,
    feature_set_id: int,
    trained_at: datetime,
    training_export_id: int | None = None,
    train_row_count: int | None = None,
    validation_row_count: int | None = None,
    metrics_json: dict | None = None,
    hyperparameters_json: dict | None = None,
    is_active: bool = False,
) -> int:
    cur.execute(
        """
        INSERT INTO model_versions (
            model_name, version, target, framework, artifact_path,
            feature_set_id, training_export_id,
            train_row_count, validation_row_count,
            metrics_json, hyperparameters_json, trained_at, is_active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (model_name, version, target, framework, artifact_path,
         feature_set_id, training_export_id,
         train_row_count, validation_row_count,
         Json(metrics_json) if metrics_json is not None else None,
         Json(hyperparameters_json) if hyperparameters_json is not None else None,
         trained_at, is_active),
    )
    return cur.fetchone()["id"]


def set_active(cur, model_version_id: int) -> None:
    """Activate one model version for its target, deactivating others for that target."""
    cur.execute("SELECT target FROM model_versions WHERE id = %s", (model_version_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"model_version {model_version_id} not found")
    target = row["target"]
    cur.execute("UPDATE model_versions SET is_active = FALSE WHERE target = %s", (target,))
    cur.execute("UPDATE model_versions SET is_active = TRUE WHERE id = %s", (model_version_id,))


def get_active(cur, target: str) -> dict | None:
    cur.execute(
        "SELECT * FROM model_versions WHERE target = %s AND is_active = TRUE LIMIT 1",
        (target,),
    )
    return cur.fetchone()


def list_all(cur, target: str | None = None) -> list[dict]:
    if target:
        cur.execute(
            "SELECT * FROM model_versions WHERE target = %s ORDER BY trained_at DESC",
            (target,),
        )
    else:
        cur.execute("SELECT * FROM model_versions ORDER BY trained_at DESC")
    return list(cur.fetchall())
