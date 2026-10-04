"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "AFFILIATE_CODE": "PP-TX-01",
    "STATE_CODE": "TX",
    "QUOTA": 50,
    "SERVICE_CODE": "CONTRACEPTIVE_COUNSELING",
    "FULL_FEE_CENTS": 20000,
    "EXTERNAL_REF": "P-0001",
    "DATE_OF_BIRTH": "1990-01-01",
    "HOUSEHOLD_SIZE": 1,
    "ANNUAL_INCOME_CENTS": 4000000,
    "INCOME_BASIS": "DOCUMENTED",
    "DISPLAY_NAME": "Dr. Test",
    "PROVIDER_TYPE": "NP",
    "LICENSE_STATE": "TX",
    "VALID_FROM": "2026-01-01T00:00:00Z",
    "VALID_UNTIL": "2027-01-01T00:00:00Z",
    "CHANNEL": "IN_PERSON",
    "SCHEDULED_START": "2026-09-10T10:00:00Z",
    "SCHEDULED_END": "2026-09-10T10:30:00Z",
    "DEVICE_CODE": "IUD_COPPER",
    "LOT_NUMBER": "LOT-1",
    "UNIT_COST_CENTS": 15000,
    "ON_HAND": 5,
    "EXPIRES_ON": "2027-01-01",
    "REQUESTED_SERVICE_CODE": "PRENATAL_CARE",
    "RECEIVING_ORG": "County Health",
    "REASON_CODE": "OUT_OF_SCOPE_AFFILIATE",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-10-01T00:00:00Z",
    "VALUATION_VARIANT": "FIFO",
    "HOLD_START": "2026-09-01T00:00:00Z",
    "HOLD_END": "2026-10-01T00:00:00Z",
    "HOLD_SCOPE": "ALL",
}


def create_affiliate_payload(**overrides) -> dict:
    defaults = {
        "affiliate_code": DEFAULTS["AFFILIATE_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "low_income_priority_quota": DEFAULTS["QUOTA"],
    }
    defaults.update(overrides)
    return defaults


def create_catalog_entry_payload(**overrides) -> dict:
    defaults = {
        "service_code": DEFAULTS["SERVICE_CODE"],
        "in_scope": True,
        "telehealth_eligible": True,
        "full_fee_cents": DEFAULTS["FULL_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_code": "D",
        "fpl_pct_min_inclusive": 0,
        "fpl_pct_max_exclusive": 1000,
        "discount_pct": 0,
        "nominal_copay_cents": 0,
        "requires_documentation": False,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "external_ref": DEFAULTS["EXTERNAL_REF"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
        "income_basis": DEFAULTS["INCOME_BASIS"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "provider_type": DEFAULTS["PROVIDER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["LICENSE_STATE"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(provider_id, **overrides) -> dict:
    defaults = {
        "service_code": DEFAULTS["SERVICE_CODE"],
        "provider_id": provider_id,
        "channel": DEFAULTS["CHANNEL"],
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
    }
    defaults.update(overrides)
    return defaults


def create_stock_lot_payload(**overrides) -> dict:
    defaults = {
        "device_code": DEFAULTS["DEVICE_CODE"],
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "on_hand": DEFAULTS["ON_HAND"],
        "expires_on": DEFAULTS["EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_device_reservation_payload(lot_id, **overrides) -> dict:
    defaults = {"lot_id": lot_id}
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "requested_service_code": DEFAULTS["REQUESTED_SERVICE_CODE"],
        "receiving_org": DEFAULTS["RECEIVING_ORG"],
        "reason_code": DEFAULTS["REASON_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_report_payload(expected_affiliate_version, **overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "valuation_variant": DEFAULTS["VALUATION_VARIANT"],
        "expected_affiliate_version": expected_affiliate_version,
    }
    defaults.update(overrides)
    return defaults


def create_privacy_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_start": DEFAULTS["HOLD_START"],
        "hold_end": DEFAULTS["HOLD_END"],
        "scope": DEFAULTS["HOLD_SCOPE"],
        "authorized_staff_ids": [],
    }
    defaults.update(overrides)
    return defaults
