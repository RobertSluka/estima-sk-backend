"""
CLI entry point for the Prague Real Estate pipeline.

Usage (via the tools container):
  docker compose run --rm ml-api python -m src.main migrate
  docker compose run --rm ml-api python -m src.main ingest /app/data/listings.json
  docker compose run --rm ml-api python -m src.main generate-market-stats
  docker compose run --rm ml-api python -m src.main generate-features --name base --version v1 --target sale_price
  docker compose run --rm ml-api python -m src.main export-ml-dataset --feature-set <id> /app/data/ds.csv
  docker compose run --rm ml-api python -m src.main train --feature-set <id>
  docker compose run --rm ml-api python -m src.main mark-inactive --days 3
  docker compose run --rm ml-api python -m src.main check-db
"""

import logging
import sys
from datetime import date

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)


@click.group()
def cli():
    """Prague Real Estate Intelligence Pipeline."""


@cli.command("migrate")
def migrate_cmd():
    """Apply pending SQL migrations from sql/migrations/."""
    from src.migrate import run_migrations

    applied = run_migrations()
    if applied:
        click.echo(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        click.echo("Database is up to date — no migrations to apply.")


@cli.command("ingest")
@click.argument("filepath")
@click.option("--source", default=None, help="Run-level source label (auto-detected if omitted).")
@click.option("--apify-actor-id", default=None)
@click.option("--apify-task-id", default=None)
@click.option("--apify-run-id", default=None)
@click.option("--apify-dataset-id", default=None)
def ingest_cmd(filepath, source, apify_actor_id, apify_task_id, apify_run_id, apify_dataset_id):
    """Ingest listings from a JSON file into the database."""
    from src.services.ingestion import ingest_file

    apify_meta = {
        "actor_id": apify_actor_id, "task_id": apify_task_id,
        "run_id": apify_run_id, "dataset_id": apify_dataset_id,
    }
    try:
        stats = ingest_file(filepath, source=source, apify_meta=apify_meta)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Ingestion complete — new: {stats['new_properties']}, "
        f"updated: {stats['updated_properties']}, "
        f"price changes: {stats['price_changes']}, failed: {stats['failed']}, "
        f"market stat rows: {stats.get('market_stat_rows', 0)}"
    )


@cli.command("mark-inactive")
@click.option("--days", default=3, show_default=True,
              help="Mark properties not seen within this many days as inactive.")
def mark_inactive_cmd(days: int):
    """Mark stale listings as inactive after a full scrape run."""
    from src.db import get_cursor
    from src.repositories import properties

    with get_cursor() as cur:
        count = properties.mark_inactive(cur, days)
    click.echo(f"Marked {count} properties as inactive.")


@cli.command("geocode-streets")
@click.option("--limit", default=500, show_default=True,
              help="Maximum properties to process in this run.")
@click.option("--retry-missing", is_flag=True, default=False,
              help="Also retry properties whose previous attempt found no street position.")
def geocode_streets_cmd(limit: int, retry_missing: bool):
    """Extract street names from listing text and geocode them (Nominatim, cached)."""
    from src.services.street_geocoding import run

    stats = run(limit=limit, retry_missing=retry_missing)
    click.echo(
        f"Processed {stats.processed}: {stats.with_street} had a street mention, "
        f"{stats.geocoded} geocoded to street level."
    )


@cli.command("generate-market-stats")
@click.option("--date", "stat_date", default=None,
              help="Date to compute stats for (YYYY-MM-DD). Defaults to today.")
def generate_market_stats_cmd(stat_date: str | None):
    """Aggregate active listings into market_statistics (deal_type-aware)."""
    from src.services.market_statistics import generate

    target = date.fromisoformat(stat_date) if stat_date else None
    count = generate(target)
    click.echo(f"Generated {count} market stat rows.")


@cli.command("generate-features")
@click.option("--name", required=True, help="Feature set name.")
@click.option("--version", default="v1", show_default=True)
@click.option("--target", required=True,
              type=click.Choice(["sale_price", "rent_price",
                                 "sale_price_per_sqm", "rent_price_per_sqm"]))
def generate_features_cmd(name: str, version: str, target: str):
    """Materialize property_features for the latest snapshots."""
    from src.services.feature_generation import generate_features

    result = generate_features(name=name, version=version, target=target)
    click.echo(f"Feature set {result['feature_set_id']}: wrote {result['rows']} feature rows.")


@cli.command("export-ml-dataset")
@click.argument("output_path")
@click.option("--feature-set", "feature_set_id", type=int, required=True,
              help="feature_sets.id to export.")
def export_ml_dataset_cmd(output_path: str, feature_set_id: int):
    """Export a feature set's property_features to CSV (+ ml_dataset_exports row)."""
    from src.services.training_export import export_dataset

    row_count, export_id = export_dataset(feature_set_id, output_path)
    click.echo(f"Exported {row_count} rows to {output_path} (export id {export_id}).")


@cli.command("train")
@click.option("--feature-set", "feature_set_id", type=int, required=True)
@click.option("--model-name", default=None, help="Defaults to '<target>_xgb'.")
@click.option("--version", default=None, help="Defaults to a UTC timestamp.")
@click.option("--activate/--no-activate", default=True, show_default=True)
def train_cmd(feature_set_id, model_name, version, activate):
    """Train a minimal XGBoost model on a feature set and register it."""
    from src.services.training import train

    result = train(feature_set_id, model_name=model_name, version=version, activate=activate)
    click.echo(f"Trained model_version {result['model_version_id']} "
               f"({result['model_name']} {result['version']}) — metrics: {result['metrics']}")


@cli.command("save-property")
@click.option("--user", "user_id", required=True, help="Opaque user id.")
@click.option("--property", "property_id", type=int, required=True)
def save_property_cmd(user_id: str, property_id: int):
    """Save/like a property for a user."""
    from src.services.saved import save_property

    created = save_property(user_id, property_id)
    click.echo("Saved." if created else "Already saved.")


@cli.command("unsave-property")
@click.option("--user", "user_id", required=True)
@click.option("--property", "property_id", type=int, required=True)
def unsave_property_cmd(user_id: str, property_id: int):
    """Remove a saved property for a user."""
    from src.services.saved import unsave_property

    removed = unsave_property(user_id, property_id)
    click.echo("Removed." if removed else "Was not saved.")


@cli.command("list-saved")
@click.option("--user", "user_id", required=True)
def list_saved_cmd(user_id: str):
    """List a user's saved properties."""
    from src.services.saved import list_saved

    rows = list_saved(user_id)
    if not rows:
        click.echo("No saved properties.")
        return
    for r in rows:
        price = r["current_price"]
        click.echo(f"  #{r['property_id']:>7} [{r['deal_type']}] {r['layout'] or '?':<6} "
                   f"{(r['locality'] or '')[:32]:<32} {price if price is not None else '-':>10}  {r['url']}")
    click.echo(f"{len(rows)} saved propert{'y' if len(rows) == 1 else 'ies'}.")


@cli.command("scrape")
@click.option("--source", type=click.Choice(["sreality", "bezrealitky"]), required=True)
@click.option("--deal-type", type=click.Choice(["buy", "rent"]), required=True)
@click.option("--max-items", default=5000, show_default=True)
@click.option("--dataset-id", default=None,
              help="Skip the actor run and ingest an existing Apify dataset instead.")
def scrape_cmd(source: str, deal_type: str, max_items: int, dataset_id: str | None):
    """Trigger an Apify actor (or read a dataset), then ingest the results."""
    from src import config
    from src.services import apify
    from src.services.ingestion import ingest_items

    if dataset_id:
        result = apify.fetch_dataset(dataset_id)
    else:
        actor_id = (config.APIFY_SREALITY_ACTOR_ID if source == "sreality"
                    else config.APIFY_BEZREALITKY_ACTOR_ID)
        run_input = _build_actor_input(source, deal_type, max_items)
        result = apify.run_actor(actor_id, run_input)

    if not result["items"]:
        click.echo("No items returned from Apify — nothing to ingest.")
        return

    stats = ingest_items(result["items"], source=source, apify_meta=result["meta"])
    click.echo(
        f"Scrape+ingest complete ({source}/{deal_type}) — "
        f"new: {stats['new_properties']}, updated: {stats['updated_properties']}, "
        f"price changes: {stats['price_changes']}, failed: {stats['failed']}, "
        f"market stat rows: {stats.get('market_stat_rows', 0)}"
    )


def _build_actor_input(source: str, deal_type: str, max_items: int) -> dict:
    """Map (source, deal_type) to the actor-specific input. Tune per actor version."""
    if source == "sreality":
        return {
            "searchType": "prodej" if deal_type == "buy" else "pronajem",
            "estateType": "byty", "region": "Praha", "maxItems": max_items,
        }
    return {
        "offerType": "PRODEJ" if deal_type == "buy" else "PRONAJEM",
        "estateType": "BYT", "location": "Praha", "maxItems": max_items,
    }


@cli.command("check-db")
def check_db_cmd():
    """Verify the database connection is working."""
    from src.db import test_connection

    if test_connection():
        click.echo("Database connection OK.")
    else:
        click.echo("Database connection FAILED.", err=True)
        sys.exit(1)


@cli.command("import-benchmarks")
@click.argument("filepath")
def import_benchmarks_cmd(filepath: str):
    """Import an external market-benchmark CSV (e.g. Deloitte Real Index)."""
    from src.services.benchmark_import import import_csv

    try:
        stats = import_csv(filepath)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Benchmark import complete — rows: {stats['rows']}, imported: {stats['imported']}")


@cli.command("score-vision")
@click.option("--limit", default=100, show_default=True,
              help="Max properties to score in this run.")
@click.option("--rescore", is_flag=True, default=False,
              help="Re-score properties that already have a vision score.")
def score_vision_cmd(limit: int, rescore: bool):
    """Score listing galleries via the vision service into vision_scores."""
    from src.services.vision_scoring import run

    stats = run(limit=limit, rescore=rescore)
    click.echo(
        f"Vision scoring complete — scored: {stats['scored']}, "
        f"failed: {stats['failed']}, pending: {stats['pending']}"
    )


@cli.command("warm-locations")
@click.option("--limit", default=100, show_default=True,
              help="Max properties to process in this run.")
@click.option("--rescore", is_flag=True, default=False,
              help="Recompute properties that already have a cached location score.")
@click.option("--rate", default=0.5, show_default=True,
              help="Max Overpass requests per second (politeness throttle; "
                   "the public instance 429s above ~1/sec under load).")
def warm_locations_cmd(limit: int, rescore: bool, rate: float):
    """Precompute nearby-facility counts via Overpass into location_scores.

    Report generation (src/services/reports/builder.py) reads this table
    first and only falls back to a live Overpass call when a property is
    missing from it — so running this ahead of time is what makes report
    generation fast for previously-warmed properties, including right after a
    process restart (unlike the in-process cache in geo.py, this persists).
    """
    from src.services.location_scoring import run

    stats = run(limit=limit, rescore=rescore, rate=rate)
    click.echo(
        f"Location warmup complete — scored: {stats['scored']}, "
        f"failed: {stats['failed']}, pending: {stats['pending']}"
    )


if __name__ == "__main__":
    cli()
