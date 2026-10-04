"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_studio_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["STUDIO_NAME"],
        "ad_budget_cents": TEST_DEFAULTS["STUDIO_AD_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = {
        "studio_id": None,
        "year": TEST_DEFAULTS["SEASON_YEAR"],
        "label": TEST_DEFAULTS["SEASON_LABEL"],
        "required_title_count": 1,
        "air_window_start": TEST_DEFAULTS["AIR_WINDOW_START"],
        "air_window_end": TEST_DEFAULTS["AIR_WINDOW_END"],
        "delivery_deadline": TEST_DEFAULTS["DELIVERY_DEADLINE"],
        "max_shoot_days": TEST_DEFAULTS["MAX_SHOOT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "name": "T1",
        "genre": "ROMANCE",
        "tone_rating": "WARM",
        "content_flags": [],
        "duration_minutes": 90,
    }
    defaults.update(overrides)
    return defaults


def create_talent_payload(**overrides) -> dict:
    defaults = {
        "studio_id": None,
        "stage_name": "Holly Star",
        "availability_windows": [],
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(**overrides) -> dict:
    defaults = {
        "talent_id": None,
        "season_id": None,
        "picture_commitment": 1,
    }
    defaults.update(overrides)
    return defaults


def create_casting_payload(**overrides) -> dict:
    defaults = {
        "title_id": None,
        "talent_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(**overrides) -> dict:
    defaults = {
        "studio_id": None,
        "name": "Stage A",
        "blackout_windows": [],
    }
    defaults.update(overrides)
    return defaults


def create_production_slot_payload(**overrides) -> dict:
    defaults = {
        "title_id": None,
        "location_id": None,
        "shoot_start": TEST_DEFAULTS["SHOOT_START"],
        "shoot_end": TEST_DEFAULTS["SHOOT_END"],
        "shoot_days": TEST_DEFAULTS["SHOOT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_program_block_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "name": TEST_DEFAULTS["BLOCK_NAME"],
        "block_start": TEST_DEFAULTS["BLOCK_START"],
        "premiere_cadence_days": TEST_DEFAULTS["PREMIERE_CADENCE_DAYS"],
        "max_encores_per_title": TEST_DEFAULTS["MAX_ENCORES_PER_TITLE"],
        "min_minutes_between_airings": 1440,
    }
    defaults.update(overrides)
    return defaults


def create_air_slot_payload(**overrides) -> dict:
    defaults = {
        "block_id": None,
        "title_id": None,
        "air_start": TEST_DEFAULTS["BLOCK_START"],
        "kind": "PREMIERE",
        "expected_block_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_sponsorship_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "advertiser": "CardsCo",
        "season_cpm_cents": 2000,
        "viewership_thousands": 10,
    }
    defaults.update(overrides)
    return defaults


def create_streaming_window_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "title_id": None,
        "platform": "OWN_STREAMER",
        "window_start": "2027-11-06T00:00:00Z",
        "window_end": "2027-12-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "title_id": None,
        "category": "MERCHANDISE",
        "licensee": "OrnamentWorks",
        "royalty_rate": 0.10,
        "reported_revenue_cents": 1500000,
    }
    defaults.update(overrides)
    return defaults
