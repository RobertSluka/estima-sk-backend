"""
Minimal XGBoost trainer.

Loads a feature set's leakage-free features, trains an XGBRegressor on a log1p
target, saves the full sklearn pipeline as a joblib artifact, records the
training export, and registers the model in model_versions.

Deliberately minimal — there is only ~1 day of snapshots so far; this is the
runnable skeleton, not a tuned model.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBRegressor

from src import config
from src.config import ARTIFACTS_DIR
from src.repositories.vision_scores import SCORE_FIELDS as VISION_SCORE_FIELDS
from src.services import model_registry
from src.services.training_export import load_dataframe

logger = logging.getLogger(__name__)

CATEGORICAL = ["source", "deal_type", "category", "locality", "district", "layout"]
# vision_* scores are materialized into every feature set, but the model only
# consumes them when VISION_FEATURES_ENABLED is on (off by default — too few
# scored listings to help yet). Flip the env var and retrain to switch them in.
_VISION_NUMERIC = [f"vision_{field}" for field in VISION_SCORE_FIELDS]
NUMERIC = ["layout_encoded", "floor_area", "land_area", "lat", "lon",
           "market_median_price", "market_median_price_per_sqm", "market_property_count",
           *(_VISION_NUMERIC if config.VISION_FEATURES_ENABLED else [])]

DEFAULT_PARAMS = dict(
    n_estimators=200, max_depth=5, learning_rate=0.1,
    subsample=0.9, colsample_bytree=0.9, random_state=42,
)


def train(feature_set_id: int, *, model_name: str | None = None,
          version: str | None = None, activate: bool = True) -> dict:
    df, target = load_dataframe(feature_set_id)
    if len(df) < 5:
        raise ValueError(f"Not enough rows to train ({len(df)}); generate more snapshots first.")

    model_name = model_name or f"{target}_xgb"
    version = version or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    cat_cols = [c for c in CATEGORICAL if c in df.columns]
    num_cols = [c for c in NUMERIC if c in df.columns]
    X = df[cat_cols + num_cols]
    y = df["target"].astype(float)
    y_log = np.log1p(y)

    # Time-aware-ish holdout when there is enough data; otherwise evaluate on train.
    if len(df) >= 20:
        X_tr, X_val, y_tr, y_val = train_test_split(X, y_log, test_size=0.2, random_state=42)
    else:
        X_tr, X_val, y_tr, y_val = X, X, y_log, y_log

    pipeline = Pipeline([
        ("prep", ColumnTransformer([
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cat_cols),
            ("num", SimpleImputer(strategy="median"), num_cols),
        ])),
        ("model", XGBRegressor(**DEFAULT_PARAMS)),
    ])
    pipeline.fit(X_tr, y_tr)

    pred = np.expm1(pipeline.predict(X_val))
    actual = np.expm1(y_val)
    metrics = {
        "mae": round(float(mean_absolute_error(actual, pred)), 2),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, pred))), 2),
        "r2": round(float(r2_score(actual, pred)), 4) if len(actual) > 1 else None,
    }

    artifacts = Path(ARTIFACTS_DIR)
    artifacts.mkdir(parents=True, exist_ok=True)
    artifact_path = str(artifacts / f"{model_name}_{version}.joblib")
    joblib.dump(
        {"pipeline": pipeline, "cat_cols": cat_cols, "num_cols": num_cols,
         "target": target, "log_target": True},
        artifact_path,
    )

    # Lineage: write a CSV export row alongside the model.
    from src.services.training_export import export_dataset
    _, export_id = export_dataset(feature_set_id, str(artifacts / f"{model_name}_{version}.csv"),
                                  notes=f"training export for {model_name} {version}")

    model_version_id = model_registry.register(
        model_name=model_name, version=version, target=target, framework="xgboost",
        artifact_path=artifact_path, feature_set_id=feature_set_id,
        training_export_id=export_id,
        train_row_count=len(X_tr), validation_row_count=len(X_val),
        metrics=metrics, hyperparameters=DEFAULT_PARAMS, activate=activate,
    )

    logger.info("Trained %s %s — metrics=%s artifact=%s", model_name, version, metrics, artifact_path)
    return {"model_version_id": model_version_id, "model_name": model_name,
            "version": version, "metrics": metrics, "artifact_path": artifact_path}
