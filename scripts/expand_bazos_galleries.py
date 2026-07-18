"""Expand stored Bazoš listings' single thumbnail into the full photo gallery.

Usage (from the repo root, or inside the read-api container):

    python -m scripts.expand_bazos_galleries [--limit N] [--dry-run]

Idempotent: only touches bazos rows whose ``images`` still holds at most one
URL, probes Bazoš gently (sequential HEADs with a small pause), and updates
``properties.images`` in place. Run after each Bazoš ingest.
"""
from __future__ import annotations

import argparse
import json
import time

from src.db import get_cursor
from src.services.bazos_gallery import expand_gallery

# Pause between listings, on top of sequential probing — be a polite client.
_SLEEP_BETWEEN_LISTINGS = 0.2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import requests

    session = requests.Session()

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT id, image_url FROM properties
            WHERE source = 'bazos' AND image_url IS NOT NULL
              AND COALESCE(jsonb_array_length(images), 0) <= 1
            ORDER BY id
            """
        )
        rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} bazos properties to expand")
    expanded = skipped = 0
    for row in rows:
        gallery = expand_gallery(row["image_url"], session=session)
        if len(gallery) <= 1:
            skipped += 1
            continue
        expanded += 1
        print(f"property {row['id']}: {len(gallery)} photos")
        if not args.dry_run:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE properties SET images = %s WHERE id = %s",
                    (json.dumps(gallery), row["id"]),
                )
        time.sleep(_SLEEP_BETWEEN_LISTINGS)

    print(f"done — expanded: {expanded}, single-photo: {skipped}"
          + (" (dry run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
