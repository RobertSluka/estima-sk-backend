"""
Saved/liked properties service.

Thin orchestration over the saved_properties repository, each call in its own
transaction. user_id is an opaque external identifier (auth lives elsewhere).
"""

import logging

from src.db import get_cursor
from src.repositories import saved_properties

logger = logging.getLogger(__name__)


def save_property(user_id: str, property_id: int) -> bool:
    """Save a property for a user. Returns True if newly saved."""
    with get_cursor() as cur:
        created = saved_properties.save(cur, user_id, property_id)
    logger.info("save_property user=%s property=%s newly_saved=%s",
                user_id, property_id, created)
    return created


def unsave_property(user_id: str, property_id: int) -> bool:
    """Remove a saved property. Returns True if it was removed."""
    with get_cursor() as cur:
        removed = saved_properties.unsave(cur, user_id, property_id)
    return removed


def is_saved(user_id: str, property_id: int) -> bool:
    with get_cursor(commit=False) as cur:
        return saved_properties.is_saved(cur, user_id, property_id)


def list_saved(user_id: str) -> list[dict]:
    with get_cursor(commit=False) as cur:
        return saved_properties.list_for_user(cur, user_id)
