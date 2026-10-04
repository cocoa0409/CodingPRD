"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_item_seq = {"n": 0}


def create_club_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["CLUB_NAME"],
        "open_minute": TEST_DEFAULTS["OPEN_MINUTE"],
        "early_shopping_start_minute": TEST_DEFAULTS["EARLY_START_MINUTE"],
        "exit_verification_mode": TEST_DEFAULTS["EXIT_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(**overrides) -> dict:
    _item_seq["n"] += 1
    defaults = {
        "sku": f"SKU-{_item_seq['n']:05d}",
        "item_name": f"Test Item {_item_seq['n']}",
        "pricing_mode": "UNIT",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    # A None override removes the key (e.g. unit_price_cents on a WEIGHTED
    # item), keeping payloads pricing-mode-consistent.
    return {k: v for k, v in defaults.items() if v is not None}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "tier": "CLUB",
        "birth_year": TEST_DEFAULTS["BIRTH_YEAR"],
    }
    defaults.update(overrides)
    if "home_club_id" not in defaults:
        raise ValueError("create_member_payload requires home_club_id")
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "discount_cents": 100,
        "valid_from_iso": "2026-01-01T00:00:00Z",
        "valid_to_iso": "2026-12-31T23:59:59Z",
        "per_member_limit": 5,
    }
    defaults.update(overrides)
    if "catalog_item_id" not in defaults:
        raise ValueError("create_offer_payload requires catalog_item_id")
    return defaults


def create_scan_line_payload(**overrides) -> dict:
    defaults = {"quantity": 1}
    defaults.update(overrides)
    if "catalog_item_id" not in defaults:
        raise ValueError("create_scan_line_payload requires catalog_item_id")
    return defaults


def create_stage_payload(**overrides) -> dict:
    defaults = {
        "staging_slot_label": "S1",
        "window_start_iso": TEST_DEFAULTS["WINDOW_START_ISO"],
        "window_end_iso": TEST_DEFAULTS["WINDOW_END_ISO"],
    }
    defaults.update(overrides)
    return defaults
