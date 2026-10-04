"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PRODUCTION_TITLE": "Test Production",
    "PRODUCTION_TYPE": "ORIGINAL",
    "BASE_PRICE_CENTS": 10000,
    "ASSET_TITLE": "Test Asset",
    "CAPTURE_FORMAT": "WRAP_8K",
    "STORAGE_GB": 100,
    "RENDER_HOURS_BASE": 2,
    "SHOW_FORMAT": "FILM",
    "SHOW_START": "2026-09-03T19:00:00Z",
    "SHOW_LENGTH_MINUTES": 90,
    "SPONSOR_NAME": "Test Sponsor",
    "BRAND_TIER": "STANDARD",
    "CAMPAIGN_START": "2026-08-31T00:00:00Z",
    "CAMPAIGN_END": "2026-09-30T00:00:00Z",
    "EXTERIOR_SLOTS": 1,
    "SPOT_SECONDS": 30,
    "CONTRACTED_IMPRESSIONS": 5000,
    "SYSTEM_NAME": "Test System",
    "SYSTEM_KIND": "ENV_FX",
    "WINDOW_START": "2026-09-05T01:00:00Z",
    "WINDOW_END": "2026-09-05T02:00:00Z",
    "BUFFER_MINUTES": 15,
}


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PRODUCTION_TITLE"],
        "production_type": DEFAULTS["PRODUCTION_TYPE"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "is_haptic_capable": False,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "title": DEFAULTS["ASSET_TITLE"],
        "capture_format": DEFAULTS["CAPTURE_FORMAT"],
        "storage_gb": DEFAULTS["STORAGE_GB"],
        "render_hours_base": DEFAULTS["RENDER_HOURS_BASE"],
    }
    defaults.update(overrides)
    return defaults


def create_render_batch_payload(asset_ids, **overrides) -> dict:
    defaults = {
        "dispatch_mode": "STANDARD",
        "asset_ids": list(asset_ids),
    }
    defaults.update(overrides)
    return defaults


def create_show_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "show_format": DEFAULTS["SHOW_FORMAT"],
        "start_time": DEFAULTS["SHOW_START"],
        "length_minutes": DEFAULTS["SHOW_LENGTH_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "zone": "MAIN",
        "seats": 1,
    }
    defaults.update(overrides)
    return defaults


def create_venue_system_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SYSTEM_NAME"],
        "kind": DEFAULTS["SYSTEM_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(venue_system_id, **overrides) -> dict:
    defaults = {
        "venue_system_id": venue_system_id,
        "start_time": DEFAULTS["WINDOW_START"],
        "end_time": DEFAULTS["WINDOW_END"],
        "buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SPONSOR_NAME"],
        "brand_tier": DEFAULTS["BRAND_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(sponsor_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "start_time": DEFAULTS["CAMPAIGN_START"],
        "end_time": DEFAULTS["CAMPAIGN_END"],
        "exterior_slots": DEFAULTS["EXTERIOR_SLOTS"],
        "spot_seconds": DEFAULTS["SPOT_SECONDS"],
        "contracted_impressions": DEFAULTS["CONTRACTED_IMPRESSIONS"],
    }
    defaults.update(overrides)
    return defaults
