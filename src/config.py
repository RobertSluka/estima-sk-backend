import os
from pathlib import Path
from dotenv import load_dotenv

# When running locally outside Docker, load from .env at project root.
# Inside Docker, DATABASE_URL is injected by docker-compose and load_dotenv is a no-op.
load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://estima_sk:changeme@localhost:5433/estima_sk",
)

APIFY_API_TOKEN: str = os.environ.get("APIFY_API_TOKEN", "")

# TODO(Phase 2 — SK scraper): these are the inherited CZ actor slugs. The
# Slovak scraper rewrite (apify_runner/ + `src.main scrape`) replaces them with
# nehnutelnosti.sk / topreality.sk / reality.sk actors. Left as-is for now so
# the CZ scrape CLI stays import-clean; unused by the read API.
APIFY_SREALITY_ACTOR_ID: str = os.environ.get(
    "APIFY_SREALITY_ACTOR_ID", "petr_cermak/sreality-scraper"
)
APIFY_BEZREALITKY_ACTOR_ID: str = os.environ.get(
    "APIFY_BEZREALITKY_ACTOR_ID", "hbc_scraping/bezrealitky"
)
APIFY_TIMEOUT_SECONDS: int = int(os.environ.get("APIFY_TIMEOUT_SECONDS", "600"))
APIFY_POLL_INTERVAL_SECONDS: int = int(os.environ.get("APIFY_POLL_INTERVAL_SECONDS", "15"))

# Where trained model artifacts are written (mounted Docker volume in prod).
ARTIFACTS_DIR: str = os.environ.get("ARTIFACTS_DIR", "artifacts")

# Vision scoring microservice (vision-scoring-service). The bridge POSTs listing
# galleries to {VISION_SERVICE_URL}/score and stores the returned quality scores.
VISION_SERVICE_URL: str = os.environ.get("VISION_SERVICE_URL", "http://localhost:8000")
VISION_SCORE_TIMEOUT_SECONDS: int = int(os.environ.get("VISION_SCORE_TIMEOUT_SECONDS", "60"))
VISION_MAX_IMAGES: int = int(os.environ.get("VISION_MAX_IMAGES", "50"))

# On-demand scoring path used by report generation (src/services/reports/builder.py)
# when a property has no cached vision_scores row yet. Tighter than the batch
# job's bounds — fewer images (each downloaded synchronously inside the
# request) and a short timeout — so a slow/unreachable vision service
# degrades the report's vision section instead of stalling PDF generation.
VISION_ON_DEMAND_TIMEOUT_SECONDS: int = int(
    os.environ.get("VISION_ON_DEMAND_TIMEOUT_SECONDS", "12")
)
VISION_ON_DEMAND_MAX_IMAGES: int = int(os.environ.get("VISION_ON_DEMAND_MAX_IMAGES", "8"))

# Whether trained models consume the vision_* quality scores. OFF by default:
# the gallery/bridge keep collecting scores into vision_scores, but the model
# ignores them until there's enough scored data to be worth it. Flip to true
# (env VISION_FEATURES_ENABLED=true) and retrain to switch them on.
VISION_FEATURES_ENABLED: bool = os.environ.get(
    "VISION_FEATURES_ENABLED", "false"
).lower() in ("1", "true", "yes")

# OpenStreetMap Overpass endpoint used by report generation to count nearby
# facilities (src/services/reports/geo.py). The timeout is deliberately short:
# a slow or unreachable Overpass must degrade the location section, not stall
# the whole PDF.
OVERPASS_URL: str = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_TIMEOUT_SECONDS: int = int(os.environ.get("OVERPASS_TIMEOUT_SECONDS", "20"))

# On-disk cache for rendered static maps (src/services/reports/geo.py), keyed
# by rounded coordinate. OSM's tile-server usage policy explicitly discourages
# bulk/scripted downloading, so each coordinate's tiles are fetched at most
# once ever (not once per process restart) — this directory is what makes
# that durable across restarts and separate batch-job runs.
LOCATION_MAP_CACHE_DIR: str = os.environ.get("LOCATION_MAP_CACHE_DIR", "data/location_maps")

# Same idea for the nearest-named-facility Overpass lookups: Overpass asks for
# restraint from scripted clients, so each coordinate's nearest-POI answer is
# fetched once ever and kept on disk as JSON.
LOCATION_POI_CACHE_DIR: str = os.environ.get("LOCATION_POI_CACHE_DIR", "data/location_pois")

# Galleries whose last scoring attempt analysed zero images (dead URLs) are
# retried at most once per this many days, so permanently delisted photo sets
# don't get re-downloaded on every batch run. `score-vision --rescore`
# ignores the cool-down.
VISION_EMPTY_RETRY_DAYS: int = int(os.environ.get("VISION_EMPTY_RETRY_DAYS", "7"))

# estima-report-service integration for /reports/properties/{id}/pdf. When set
# (e.g. http://host.docker.internal:8090), the endpoint builds a payload —
# including the NBS market_statistics block — and lets the report service
# render the PDF; on any failure it falls back to the internal WeasyPrint
# pipeline. Empty (the default) keeps the internal pipeline as the only path,
# so existing deployments are unaffected.
REPORT_SERVICE_URL: str = os.environ.get("REPORT_SERVICE_URL", "")
REPORT_SERVICE_TIMEOUT_SECONDS: int = int(os.environ.get("REPORT_SERVICE_TIMEOUT_SECONDS", "60"))

# Shared secret for the /internal/* account & billing endpoints consumed by the
# estima-sk Next.js server (never by browsers). Empty (default) disables those
# endpoints entirely — fail closed, mirroring the frontend's ADMIN_PASSWORD rule.
INTERNAL_API_KEY: str = os.environ.get("INTERNAL_API_KEY", "")
