"""
Prediction service.

Loads the active model for a target, builds a single feature row from the request
(the same leakage-free features used in training), predicts, logs to predictions,
and returns the result. Confidence intervals are not modelled yet (returned None).
"""

import logging

import joblib
import numpy as np
import pandas as pd

from src.db import get_cursor
from src.repositories import predictions
from src.services import model_registry
from src.services.feature_generation import layout_encoded

logger = logging.getLogger(__name__)


def predict(request: dict, *, target: str, property_id: int | None = None) -> dict:
    """
    request: a dict of listing attributes, e.g.
        {"source": "sreality", "deal_type": "buy", "category": "apartment",
         "locality": "Praha 5", "district": "Praha 5", "layout": "2+kk",
         "floor_area": 50, "lat": 50.07, "lon": 14.39,
         "market_median_price": 8000000, "market_property_count": 120}
    target: one of sale_price / rent_price / sale_price_per_sqm / rent_price_per_sqm
    """
    model = model_registry.get_active(target)
    if not model:
        raise ValueError(f"No active model for target '{target}'. Train one first.")

    bundle = joblib.load(model["artifact_path"])
    pipeline = bundle["pipeline"]
    cat_cols, num_cols = bundle["cat_cols"], bundle["num_cols"]

    features = _build_features(request, cat_cols, num_cols)
    X = pd.DataFrame([{c: features.get(c) for c in cat_cols + num_cols}])

    raw_pred = float(pipeline.predict(X)[0])
    value = float(np.expm1(raw_pred)) if bundle.get("log_target") else raw_pred

    per_sqm = target.endswith("per_sqm")
    predicted_price = None if per_sqm else int(round(value))
    predicted_price_per_sqm = round(value, 2) if per_sqm else None

    with get_cursor() as cur:
        prediction_id = predictions.insert(
            cur,
            model_version_id=model["id"],
            property_id=property_id,
            request_json=request,
            features_json=features,
            predicted_price=predicted_price,
            predicted_price_per_sqm=predicted_price_per_sqm,
        )

    logger.info("Prediction %d via model_version %d (%s) → %s",
                prediction_id, model["id"], target, value)
    return {
        "prediction_id": prediction_id,
        "model_version_id": model["id"],
        "target": target,
        "predicted_price": predicted_price,
        "predicted_price_per_sqm": predicted_price_per_sqm,
        "confidence_low": None,
        "confidence_high": None,
    }


def _build_features(request: dict, cat_cols: list[str], num_cols: list[str]) -> dict:
    """Assemble the feature dict the model expects from a raw request."""
    features = {c: request.get(c) for c in cat_cols + num_cols}
    if "layout_encoded" in num_cols and features.get("layout_encoded") is None:
        features["layout_encoded"] = layout_encoded(request.get("layout"))
    return features
