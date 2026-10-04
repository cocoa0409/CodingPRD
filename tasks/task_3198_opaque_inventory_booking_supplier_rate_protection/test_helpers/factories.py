"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)

DEFAULTS = {
    "LEGAL_NAME": "Acme Hospitality",
    "BRAND_NAME": "Acme Grand",
    "FULL_NAME": "Test Customer",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "opaque_commission_pct": TEST_DEFAULTS["SUPPLIER_COMMISSION_PCT"],
        "concealment_discount_min_pct": TEST_DEFAULTS["SUPPLIER_MIN_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "brand_name": DEFAULTS["BRAND_NAME"],
        "star_rating": 4,
        "neighborhood_code": "NB1",
        "amenity_codes": ["POOL"],
        "published_rate_cents": TEST_DEFAULTS["PUBLISHED_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_window_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "check_in_date": TEST_DEFAULTS["WINDOW_CHECK_IN"],
        "check_out_date": TEST_DEFAULTS["WINDOW_CHECK_OUT"],
        "opaque_rate_cents": TEST_DEFAULTS["OPAQUE_RATE_CENTS"],
        "rooms_allocated": TEST_DEFAULTS["ROOMS_ALLOCATED"],
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_zone_payload(**overrides) -> dict:
    defaults = {
        "neighborhood_code": "NB1",
        "min_star_rating": 3,
        "revealed_amenity_codes": ["POOL"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": f"customer{next(_email_counter)}@example.com",
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_opaque_bid_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "neighborhood_code": "NB1",
        "min_star_rating": 4,
        "check_in_date": TEST_DEFAULTS["STAY_CHECK_IN"],
        "check_out_date": TEST_DEFAULTS["STAY_CHECK_OUT"],
        "offer_mode": "FIXED",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_case_payload(booking_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "category": "OTHER",
        "description": "Test complaint",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_batch_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "period_start_date": "2026-10-01T00:00:00Z",
        "period_end_date": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fraud_flag_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "reason_code": "MANUAL_REVIEW",
        "score_delta": 30,
    }
    defaults.update(overrides)
    return defaults
