"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_agency_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["HOME_AGENCY"])
    defaults.update(overrides)
    return defaults


def create_away_agency_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["AWAY_AGENCY"])
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "plaza_code": "P1",
        "vehicle_class": "CLASS_2",
        "base_rate_cents": 800,
        "axle_multiplier": 1.0,
        "peak_multiplier": 1.0,
        "image_fee_cents": 100,
        "effective_from": TEST_DEFAULTS["WINDOW_FROM"],
        "effective_to": TEST_DEFAULTS["WINDOW_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_discount_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": "STD",
        "discount_pct": 0.0,
        "daily_discount_cap_cents": 0,
        "applies_to_agency_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "holder_name": "Test Holder",
        "holder_email": "holder@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_transponder_payload(**overrides) -> dict:
    defaults = {
        "tag_number": "TAG-1",
        "vehicle_class": "CLASS_2",
        "plate_number": "ABC123",
        "plate_state": "NY",
    }
    defaults.update(overrides)
    return defaults


def create_toll_transaction_payload(**overrides) -> dict:
    defaults = {
        "plaza_code": "P1",
        "trip_timestamp": "2026-09-02T09:00:00Z",
        "is_peak": False,
        "idempotency_key": "key-1",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "dispute_type": "VEHICLE_CLASSIFICATION",
    }
    defaults.update(overrides)
    return defaults


def create_plate_data_agreement_payload(**overrides) -> dict:
    defaults = {
        "effective_from": TEST_DEFAULTS["WINDOW_FROM"],
        "effective_to": TEST_DEFAULTS["AGREEMENT_WINDOW_TO"],
        "covers_states": ["NY"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_file_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
