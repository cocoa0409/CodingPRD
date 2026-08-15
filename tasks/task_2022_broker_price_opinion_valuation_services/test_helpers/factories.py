"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    CLOCK_START,
    DEFAULT_AGREED_FEE_CENTS,
    DEFAULT_COMP_DISTANCE_MILES,
    DEFAULT_COMP_SALE_DATE,
    DEFAULT_COMP_SALE_PRICE_CENTS,
    DEFAULT_PHOTO_CAPTURED_AT,
    LICENSE_EXPIRES_FUTURE,
)


def create_client_account_payload(**overrides) -> dict:
    defaults = {
        "client_code": "CLAA",
        "display_name": "Test Client",
        "sla_hours_standard": 72,
        "sla_hours_rush": 24,
    }
    defaults.update(overrides)
    return defaults


def create_state_regulation_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "bpo_permitted": True,
        "appraisal_required_for_interior": False,
        "min_driveby_radius_miles": 1.0,
        "min_interior_radius_miles": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "street_address": "1 Main St",
        "city": "Springfield",
        "state_code": "CA",
        "postal_code": "90001",
        "living_area_sqft": 1500,
        "lot_area_sqft": 5000,
        "year_built": 1990,
        "property_type": "SINGLE_FAMILY",
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "broker_code": "BRKA",
        "full_name": "Test Broker",
        "email": "broker@example.com",
        "max_concurrent_orders": 5,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "license_kind": "BPO",
        "license_number": "LIC-0001",
        "expires_on": LICENSE_EXPIRES_FUTURE,
    }
    defaults.update(overrides)
    return defaults


def create_valuation_order_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "order_kind": "BPO",
        "inspection_level": "DRIVE_BY",
        "priority": "STANDARD",
        "agreed_fee_cents": DEFAULT_AGREED_FEE_CENTS,
        "client_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_comparable_payload(**overrides) -> dict:
    defaults = {
        "source_property_id": None,
        "sale_price_cents": DEFAULT_COMP_SALE_PRICE_CENTS,
        "sale_date": DEFAULT_COMP_SALE_DATE,
        "distance_miles": DEFAULT_COMP_DISTANCE_MILES,
        "adjustment_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(**overrides) -> dict:
    defaults = {
        "photo_kind": "FRONT",
        "file_url": "https://evidence.example.com/photo.jpg",
        "captured_at": DEFAULT_PHOTO_CAPTURED_AT,
    }
    defaults.update(overrides)
    return defaults


def create_fee_line_payload(**overrides) -> dict:
    defaults = {
        "fee_kind": "BASE",
        "description": "Base fee",
        "amount_cents": DEFAULT_AGREED_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_qc_verdict_payload(**overrides) -> dict:
    defaults = {
        "verdict": "APPROVE",
        "defects_found": 0,
        "notes": "Reviewed.",
    }
    defaults.update(overrides)
    return defaults


def create_payout_batch_payload(**overrides) -> dict:
    defaults = {
        "broker_id": None,
        "period_start": CLOCK_START,
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_volume_forecast_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "forecast_month": "2026-08",
    }
    defaults.update(overrides)
    return defaults
