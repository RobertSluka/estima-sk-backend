"""
Model registry service.

Thin orchestration over the model_versions repository: register a trained model
(artifact path + metadata), activate one model per target, and query the registry.
Model binaries live on disk (ARTIFACTS_DIR), never in Postgres.
"""

import logging
from datetime import datetime, timezone

from src.db import get_cursor
from src.repositories import model_versions

logger = logging.getLogger(__name__)


def register(
    *,
    model_name: str,
    version: str,
    target: str,
    framework: str,
    artifact_path: str,
    feature_set_id: int,
    trained_at: datetime | None = None,
    training_export_id: int | None = None,
    train_row_count: int | None = None,
    validation_row_count: int | None = None,
    metrics: dict | None = None,
    hyperparameters: dict | None = None,
    activate: bool = False,
) -> int:
    with get_cursor() as cur:
        model_version_id = model_versions.insert(
            cur,
            model_name=model_name,
            version=version,
            target=target,
            framework=framework,
            artifact_path=artifact_path,
            feature_set_id=feature_set_id,
            trained_at=trained_at or datetime.now(timezone.utc),
            training_export_id=training_export_id,
            train_row_count=train_row_count,
            validation_row_count=validation_row_count,
            metrics_json=metrics,
            hyperparameters_json=hyperparameters,
        )
        if activate:
            model_versions.set_active(cur, model_version_id)
    logger.info("Registered model_version %d (%s %s, active=%s)",
                model_version_id, model_name, version, activate)
    return model_version_id


def set_active(model_version_id: int) -> None:
    with get_cursor() as cur:
        model_versions.set_active(cur, model_version_id)


def get_active(target: str) -> dict | None:
    with get_cursor(commit=False) as cur:
        return model_versions.get_active(cur, target)


def list_models(target: str | None = None) -> list[dict]:
    with get_cursor(commit=False) as cur:
        return model_versions.list_all(cur, target)
