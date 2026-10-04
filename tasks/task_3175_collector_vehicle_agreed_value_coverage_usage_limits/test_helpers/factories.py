"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_member_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "full_name": f"Member {n}",
        "email": f"member{n}@example.com",
        "has_daily_driver": True,
        "driving_record_status": "CLEAN",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "vin": f"VIN-{n:06d}",
        "year": TEST_DEFAULTS["VEHICLE_YEAR"],
        "make": TEST_DEFAULTS["VEHICLE_MAKE"],
        "model": TEST_DEFAULTS["VEHICLE_MODEL"],
        "vehicle_class": "CLASSIC",
        "condition_grade": "GOOD",
        "storage_type": "ENCLOSED_GARAGE",
        "primary_use": "PLEASURE",
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "photo_type": "FRONT",
        "image_ref": f"img://photo-{n}",
        "captured_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_valuation_guide_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "edition": f"2026-Q3-{n}",
        "effective_date": TEST_DEFAULTS["GUIDE_EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_guide_entry_payload(**overrides) -> dict:
    defaults = {
        "vehicle_class": "CLASSIC",
        "make": TEST_DEFAULTS["VEHICLE_MAKE"],
        "year_min": TEST_DEFAULTS["GUIDE_YEAR_MIN"],
        "year_max": TEST_DEFAULTS["GUIDE_YEAR_MAX"],
        "base_value_cents": TEST_DEFAULTS["GUIDE_BASE_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(**overrides) -> dict:
    defaults = {
        "appraised_value_cents": 3_500_000,
        "appraised_at": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_auction_result_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "vehicle_class": "CLASSIC",
        "make": TEST_DEFAULTS["VEHICLE_MAKE"],
        "model": TEST_DEFAULTS["VEHICLE_MODEL"],
        "year": TEST_DEFAULTS["VEHICLE_YEAR"],
        "sale_price_cents": 3_000_000,
        "sale_date": "2026-03-01T00:00:00Z",
        "source_name": f"AuctionHouse-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_valuation_payload(**overrides) -> dict:
    defaults = {
        "method": "GUIDE_TOOL",
        "proposed_agreed_value_cents": TEST_DEFAULTS["GUIDE_BASE_VALUE_CENTS"],
        "expected_vehicle_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "vehicle_id": None,
        "valuation_id": None,
        "usage_tier": "REGULAR",
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "full_name": f"Driver {n}",
        "license_number": f"LIC-{n:05d}",
        "years_licensed": 10,
        "violations_last_3y": 0,
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(**overrides) -> dict:
    defaults = {
        "reported_miles": 100,
        "event_date": "2026-10-01T00:00:00Z",
        "event_kind": "ORDINARY",
        "expected_policy_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_repair_shop_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"Classic Works {n}",
        "specialty": "Ford",
        "hourly_rate_cents": 9_500,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "incident_date": "2026-10-01T00:00:00Z",
        "loss_type": "COLLISION",
        "description": f"Loss description {n}",
    }
    defaults.update(overrides)
    return defaults


def create_club_membership_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "tier": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_roadside_event_payload(**overrides) -> dict:
    defaults = {
        "vehicle_id": None,
        "service_type": "FLATBED_TOW",
        "event_date": "2026-10-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_club_event_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"Club Event {n}",
        "venue": f"Venue-{n}",
        "start_date": "2026-10-10T00:00:00Z",
        "end_date": "2026-10-11T00:00:00Z",
        "capacity": 50,
    }
    defaults.update(overrides)
    return defaults
