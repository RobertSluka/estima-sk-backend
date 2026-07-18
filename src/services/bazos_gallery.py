"""Derive full Bazoš photo galleries from the single list-page thumbnail.

Bazoš serves listing photos at sequential URLs:

    https://www.bazos.sk/img/<index>/<tail>/<listing_id>.jpg

The list-page scrape only carries index 1 (the thumbnail), but the remaining
indexes are discoverable with cheap HEAD probes: the CDN answers 200 for a
real photo and 404 one past the gallery's end. No detail-page scraping needed.

``scripts/expand_bazos_galleries.py`` runs this over the stored properties;
re-run it after each Bazoš ingest to pick up galleries for new listings.
"""
from __future__ import annotations

import re
from typing import Optional

# Only exact list-page thumbnails are expandable (index segment must be 1).
_IMG_RE = re.compile(r"^(https?://www\.bazos\.sk/img/)1(/.+\.jpg)$")
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Estima/1.0)"}

# The report's gallery appendix caps at 12 thumbnails; probing further would
# only cost requests against Bazoš for photos nothing renders.
MAX_PHOTOS = 12


def candidate_url(image_url: Optional[str], index: int) -> Optional[str]:
    """URL of photo ``index`` for the same listing, or None if the URL is not
    a recognizable Bazoš thumbnail."""
    match = _IMG_RE.match(image_url or "")
    if not match:
        return None
    return f"{match.group(1)}{index}{match.group(2)}"


def expand_gallery(
    image_url: Optional[str],
    *,
    max_photos: int = MAX_PHOTOS,
    timeout: float = 8.0,
    session=None,
) -> list[str]:
    """Confirmed gallery ``[img/1 .. img/k]`` for a Bazoš thumbnail URL.

    Probes sequentially and stops at the first non-200 answer, so a listing
    with k photos costs k+1 requests. Network errors end the probe early;
    the result always contains at least the original URL (when present).
    """
    if not image_url:
        return []
    if candidate_url(image_url, 2) is None:
        return [image_url]

    import requests

    sess = session or requests
    urls = [image_url]
    for index in range(2, max_photos + 1):
        url = candidate_url(image_url, index)
        try:
            resp = sess.head(
                url, timeout=timeout, headers=_HEADERS, allow_redirects=False
            )
        except requests.RequestException:
            break
        if resp.status_code != 200:
            break
        urls.append(url)
    return urls
