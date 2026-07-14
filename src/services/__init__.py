"""
Service layer for the src/ pipeline.

Services orchestrate repositories and hold business logic:
  normalizer          — raw scraper item → canonical dict
  ingestion           — run → raw_listings → properties → snapshots → price_changes → stats
  market_statistics   — daily aggregates (deal_type-aware)
  feature_generation  — snapshots → property_features (leakage-free)
  training_export     — property_features → CSV + ml_dataset_exports
  model_registry      — register / activate model_versions
  prediction          — load active model, predict, log
  training            — minimal XGBoost trainer
"""
