"""Payload factories -- one per resource, operator-supplied input fields only."""

from .constants import (
    DEFAULT_TIER_BREAKS,
    SEASON_END,
    SEASON_START,
    TERM_END,
    TERM_START,
    TEST_DEFAULTS,
    WINDOW_END,
    WINDOW_START,
)


def create_property_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROPERTY_NAME"],
        "sport_code": TEST_DEFAULTS["SPORT_CODE"],
        "season_year": TEST_DEFAULTS["SEASON_YEAR"],
        "season_start": SEASON_START,
        "season_end": SEASON_END,
        "inventory_target_value_cents": TEST_DEFAULTS[
            "INVENTORY_TARGET_VALUE_CENTS"
        ],
        "seasonality_index": TEST_DEFAULTS["SEASONALITY_INDEX"],
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(**overrides) -> dict:
    payload = {"label": "2026 Season Card", "effective_year": 2026}
    payload.update(overrides)
    return payload


def create_rate_card_line_payload(**overrides) -> dict:
    payload = {
        "asset_class": "DIGITAL_BOARD",
        "base_unit_price_cents": TEST_DEFAULTS[
            "DIGITAL_BOARD_BASE_UNIT_PRICE_CENTS"
        ],
        "tier_breaks": list(DEFAULT_TIER_BREAKS),
        "exclusivity_multiplier": TEST_DEFAULTS[
            "DIGITAL_BOARD_EXCLUSIVITY_MULTIPLIER"
        ],
    }
    payload.update(overrides)
    return payload


def create_inventory_asset_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["ASSET_NAME"],
        "asset_class": "DIGITAL_BOARD",
        "capacity_units": TEST_DEFAULTS["ASSET_CAPACITY_UNITS"],
        "changeover_buffer_minutes": TEST_DEFAULTS["CHANGEOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_sponsor_payload(**overrides) -> dict:
    payload = {
        "name": "Zephyr Cola",
        "category": "BEVERAGE",
        "contact_email": "ops@zephyr.example",
    }
    payload.update(overrides)
    return payload


def create_contract_payload(sponsor_id: str, property_id: str, **overrides) -> dict:
    payload = {
        "sponsor_id": sponsor_id,
        "property_id": property_id,
        "term_start": TERM_START,
        "term_end": TERM_END,
    }
    payload.update(overrides)
    return payload


def create_entitlement_payload(inventory_asset_id: str, **overrides) -> dict:
    payload = {
        "inventory_asset_id": inventory_asset_id,
        "clause_ref": TEST_DEFAULTS["CLAUSE_REF"],
        "promised_units": TEST_DEFAULTS["PROMISED_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_asset_booking_payload(
    entitlement_id: str,
    inventory_asset_id: str,
    expected_inventory_asset_version: int,
    **overrides,
) -> dict:
    payload = {
        "entitlement_id": entitlement_id,
        "inventory_asset_id": inventory_asset_id,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "units_booked": 4,
        "expected_inventory_asset_version": expected_inventory_asset_version,
    }
    payload.update(overrides)
    return payload


def create_proof_payload(**overrides) -> dict:
    payload = {
        "evidence_type": "IMPRESSIONS",
        "measured_value": 500_000,
        "media_uri": "s3://pop/evidence.json",
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["STAFF_NAME"],
        "hourly_rate_cents": TEST_DEFAULTS["STAFF_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_staff_assignment_payload(staff_member_id: str, **overrides) -> dict:
    payload = {
        "staff_member_id": staff_member_id,
        "shift_start": WINDOW_START,
        "shift_end": WINDOW_END,
        "role_label": TEST_DEFAULTS["ROLE_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_survey_payload(**overrides) -> dict:
    payload = {
        "satisfaction_score": 8,
        "activation_quality_score": 9,
        "reporting_quality_score": 7,
        "renewal_intent": "YES",
    }
    payload.update(overrides)
    return payload
