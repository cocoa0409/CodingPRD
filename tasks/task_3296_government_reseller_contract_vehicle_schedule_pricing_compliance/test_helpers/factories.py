"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next_duns() -> str:
    """Nine-digit DUNS, unique per call."""
    return f"9{next(_counter):08d}"[-9:]


def create_manufacturer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Manufacturer Corp",
        "duns": _next_duns(),
        "manufacturer_type": "SOFTWARE_PUBLISHER",
        "headquarters_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(manufacturer_id, **overrides) -> dict:
    defaults = {
        "manufacturer_id": manufacturer_id,
        "scope_tiers": list(TEST_DEFAULTS["SCOPE_TIERS"]),
        "mfc_discount_pct": TEST_DEFAULTS["MFC_DISCOUNT_PCT"],
        "small_business_goal_pct": TEST_DEFAULTS["SMALL_BUSINESS_GOAL_PCT"],
        "product_scope": list(TEST_DEFAULTS["PRODUCT_SCOPE"]),
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "vehicle_kind": "FED_SCHEDULE",
        "buyer_tiers": list(TEST_DEFAULTS["SCOPE_TIERS"]),
        "ceiling_cents": TEST_DEFAULTS["CEILING_CENTS"],
        "taa_required": False,
        "effective_from": TEST_DEFAULTS["TERM_START"],
        "effective_to": TEST_DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def price_line_payload(**overrides) -> dict:
    defaults = {
        "sku": "SW-1",
        "basis_price_cents": 20000,
        "offered_price_cents": 10000,
        "origin_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_price_list_payload(vehicle_id, lines=None, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "period_from": TEST_DEFAULTS["TERM_START"],
        "period_to": TEST_DEFAULTS["TERM_END"],
        "lines": lines if lines is not None else [price_line_payload()],
    }
    defaults.update(overrides)
    return defaults


def create_price_modification_payload(price_list_id, expected_price_list_version, **overrides) -> dict:
    defaults = {
        "price_list_id": price_list_id,
        "sku": "SW-1",
        "new_offered_price_cents": 9000,
        "reason_code": "PRC_TRIGGERED",
        "expected_price_list_version": expected_price_list_version,
    }
    defaults.update(overrides)
    return defaults


def create_teaming_payload(agreement_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "integrator_name": "Test Integrator Co",
        "small_business": True,
        "revenue_share_pct": 0.10,
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
        "scopes": [{"vehicle_id": vehicle_id, "sku_prefixes": ["SW-"]}],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(vehicle_id, price_list_id, lines=None, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "price_list_id": price_list_id,
        "buyer_tier": "FEDERAL",
        "lines": lines if lines is not None else [{"sku": "SW-1", "qty": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "period_label": "2026-10",
        "payment_terms_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "kind": "BILLING_ERROR",
        "amount_cents": -150000,
    }
    defaults.update(overrides)
    return defaults


def create_sales_report_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "period_label": "2026-09",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "scope": "PRICING_DISCLOSURE",
        "mfc_attestation_cents": 500000,
    }
    defaults.update(overrides)
    return defaults
