"""Payload factories — one per creatable entity, input fields only.

Factories default to the shared scenario values (region NE, system G25 at
2500000 cents annual fee with a 40-unit minimum, dealer Beacon Paint Co,
specialty line S1 at 100 cents). Everything is overridable per call.
"""
from .constants import TEST_DEFAULTS


def create_region_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["REGION_CODE"],
        "name": TEST_DEFAULTS["REGION_NAME"],
        "territory_radius_miles": TEST_DEFAULTS["TERRITORY_RADIUS_MILES"],
        "exclusivity_block_threshold_pct": TEST_DEFAULTS["EXCLUSIVITY_BLOCK_THRESHOLD_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_colorant_system_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["SYSTEM_CODE"],
        "name": TEST_DEFAULTS["SYSTEM_NAME"],
        "generation": TEST_DEFAULTS["SYSTEM_GENERATION"],
        "annual_license_fee_cents": TEST_DEFAULTS["ANNUAL_LICENSE_FEE_CENTS"],
        "min_initial_inventory_units": TEST_DEFAULTS["MIN_INITIAL_INVENTORY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(colorant_system_id, **overrides) -> dict:
    defaults = {
        "colorant_system_id": colorant_system_id,
        "code": TEST_DEFAULTS["LINE_CODE"],
        "name": TEST_DEFAULTS["LINE_NAME"],
        "channel_class": "SPECIALTY",
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(product_line_id, **overrides) -> dict:
    defaults = {
        "product_line_id": product_line_id,
        "code": "F1",
        "display_name": "Harbor Gray",
        "effective_from": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(region_id, **overrides) -> dict:
    defaults = {
        "region_id": region_id,
        "legal_name": TEST_DEFAULTS["DEALER_LEGAL_NAME"],
        "latitude": TEST_DEFAULTS["DEALER_LAT"],
        "longitude": TEST_DEFAULTS["DEALER_LON"],
        "exclusivity_attested_on": TEST_DEFAULTS["ATTESTED_ON"],
        "coop_accrual_rate": TEST_DEFAULTS["COOP_ACCRUAL_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(region_id, **overrides) -> dict:
    defaults = {
        "region_id": region_id,
        "legal_name": TEST_DEFAULTS["DEALER_LEGAL_NAME"],
        "latitude": TEST_DEFAULTS["DEALER_LAT"],
        "longitude": TEST_DEFAULTS["DEALER_LON"],
        "exclusivity_attested_on": TEST_DEFAULTS["ATTESTED_ON"],
        "coop_accrual_rate": TEST_DEFAULTS["COOP_ACCRUAL_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(dealer_id, colorant_system_id, installed_on, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "serial_no": TEST_DEFAULTS["SERIAL_NO"],
        "model": TEST_DEFAULTS["MODEL"],
        "colorant_system_id": colorant_system_id,
        "installed_on": installed_on,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(dealer_id, colorant_system_id, **overrides) -> dict:
    defaults = {"dealer_id": dealer_id, "colorant_system_id": colorant_system_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(dealer_id, product_line_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "product_line_id": product_line_id,
        "units": 40,
        "purpose": "INITIAL_STOCK",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(dealer_id, **overrides) -> dict:
    defaults = {"dealer_id": dealer_id, "company_name": TEST_DEFAULTS["CONTRACTOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_purchase_payload(contractor_account_id, product_line_id, **overrides) -> dict:
    defaults = {
        "contractor_account_id": contractor_account_id,
        "product_line_id": product_line_id,
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_coop_claim_payload(dealer_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "amount_cents": 10,
        "description": "Spring flyer",
        "activity_date": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_channel_event_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
        "channel": "INDEPENDENT",
        "sales_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_formulation_change_payload(product_line_id, **overrides) -> dict:
    defaults = {
        "product_line_id": product_line_id,
        "title": "Binder swap",
        "reason": "resin shortage",
        "effective_date": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
