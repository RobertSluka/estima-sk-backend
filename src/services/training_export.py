"""
Training dataset export: property_features → CSV (+ ml_dataset_exports row).

Flattens features_json into columns and appends the target column for the
feature set's target. The target is the only price-bearing column.
"""

import logging
from pathlib import Path

import pandas as pd

from src.db import get_connection, get_cursor
from src.repositories import feature_sets, ml_exports

logger = logging.getLogger(__name__)


def load_dataframe(feature_set_id: int) -> tuple[pd.DataFrame, str]:
    """Return (dataframe, target) for a feature set. Target column is named 'target'."""
    with get_cursor(commit=False) as cur:
        fs = feature_sets.get_by_id(cur, feature_set_id)
    if not fs:
        raise ValueError(f"feature_set {feature_set_id} not found")
    target = fs["target"]
    target_col = "target_price_per_sqm" if target.endswith("per_sqm") else "target_price"

    conn = get_connection()
    try:
        df = pd.read_sql_query(
            f"""
            SELECT snapshot_id, property_id, snapshot_date,
                   {target_col} AS target, features_json
            FROM property_features
            WHERE feature_set_id = %(fsid)s AND {target_col} IS NOT NULL
            ORDER BY snapshot_id
            """,
            conn,
            params={"fsid": feature_set_id},
        )
    finally:
        conn.close()

    if df.empty:
        return df, target

    features = pd.json_normalize(df.pop("features_json"))
    df = pd.concat([df.reset_index(drop=True), features.reset_index(drop=True)], axis=1)
    return df, target


def export_dataset(feature_set_id: int, output_path: str,
                   notes: str | None = None) -> tuple[int, int]:
    """
    Write the feature set to CSV and record an ml_dataset_exports row.

    Returns (row_count, export_id).
    """
    df, target = load_dataframe(feature_set_id)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    row_count = len(df)

    with get_cursor() as cur:
        export_id = ml_exports.insert(
            cur,
            feature_set_id=feature_set_id,
            export_path=output_path,
            target=target,
            row_count=row_count,
            notes=notes,
        )

    logger.info("Exported %d rows to %s (target=%s)", row_count, output_path, target)
    return row_count, export_id
