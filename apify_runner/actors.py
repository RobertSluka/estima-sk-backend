"""
Actor registry — the ONE place you edit to add or change scrapers.

Each entry says which Apify actor (or saved task) to run and with what input.
To add a scraper: append an Actor(...) to ACTORS. Nothing else needs to change.

  kind="actor"  → run a store/published actor by id, e.g. "user/actor-name"
  kind="task"   → run one of YOUR saved tasks by id, e.g. "tangy_motor/sreality-buy"

The `input` dict is sent as the run input. For a task it overrides the task's
saved input for that run, so your inputs stay visible and editable here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Actor:
    name: str                  # short slug used in output filenames
    actor_id: str              # actor id ("user/name") or task id
    kind: str = "actor"        # "actor" or "task"
    source: str = ""           # DB source label for ingest ("sreality"/"bezrealitky"); auto-detected if ""
    input: dict = field(default_factory=dict)
    enabled: bool = True       # set False to skip without deleting the entry


# ── Your actors / tasks ─────────────────────────────────────────────────────────
# Inputs below replicate what you have configured in the Apify console.

ACTORS: list[Actor] = [
    # Sreality - Czech Republic Real Estate — saved tasks (buy + rent)
    Actor(
        name="sreality-buy",
        actor_id="tangy_motor/sreality-buy",
        kind="task",
        source="sreality",
        input={
            "dealType": "buy",
            "excludeAgents": False,
            "fetchDetails": True,
            "location": "Praha",
            "maxItems": 500,
            "propertyType": "apartment",
            "requireBalcony": False,
            "requireElevator": False,
            "requireParking": False,
        },
    ),
    Actor(
        name="sreality-rent",
        actor_id="tangy_motor/sreality-rent",
        kind="task",
        source="sreality",
        input={
            "dealType": "rent",
            "excludeAgents": False,
            "fetchDetails": False,
            "location": "Praha",
            "maxItems": 500,
            "propertyType": "apartment",
            "requireBalcony": False,
            "requireElevator": False,
            "requireParking": False,
        },
    ),
    # CZ Reality Scraper — run the actor directly
    Actor(
        name="cz-reality",
        actor_id="martas_kristof/cz-reality-scraper",
        kind="actor",
        source="bezrealitky",
        input={
            "categories": ["byty", "domy"],
            "enableHistory": False,
            "maxListings": 500,
            "offerType": ["prodej", "pronajem"],
            "portals": ["bezrealitky"],
            "regions": ["Praha"],
        },
    ),
]
