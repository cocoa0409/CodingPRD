"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import DEFAULT_LOGICAL_CLOCK, DEFAULT_RETURN_WINDOW_DAYS

DEFAULTS = {
    "PARTNER_LEGAL_NAME": "Test Harbor Shelter",
    "PRODUCT_NAME": "Test Everyday Sock",
    "UNIT_COST_CENTS": 1150,
    "RETAIL_PRICE_CENTS": 1600,
    "QUANTITY": 2,
    "SEASON_CODE": "2026-Q3",
    "STATED_UNITS": 1000,
    "LIVE_CLOCK": DEFAULT_LOGICAL_CLOCK,
}


def create_giving_partner_payload(**overrides) -> dict:
    """Onboarding payload for a giving partner (PRD §3.1)."""
    payload = {
        "legal_name": DEFAULTS["PARTNER_LEGAL_NAME"],
        "partner_type": "HOMELESS_SHELTER",
        "operating_region": "NORTHEAST",
        "operating_state_code": "MA",
        "service_radius_miles": 50,
        "registry_id": "MA-CHR-310031",
        "ein": "400500600",
        "founded_year": 1972,
        "unduplicated_recipients_per_facility": 15000,
        # PRD §3.1: the declared `need_tier` is one of `CRITICAL`, `HIGH`,
        # `MODERATE` or `LOW`. The band's *base* is drawn from `partner_type`
        # (see the need_score prose in §3.1), so the two vocabularies must not
        # be conflated: sending a partner_type token here is a malformed body.
        "need_tier": "MODERATE",
    }
    payload.update(overrides)
    return payload


def create_capacity_profile_payload(**overrides) -> dict:
    """Capacity ceiling declaration for a partner and season (PRD §3.2)."""
    payload = {
        "season_code": DEFAULTS["SEASON_CODE"],
        "max_allocatable_units": 100000,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-01-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_vetting_round_payload(**overrides) -> dict:
    """Evidence + outcome write for an open vetting round (PRD §3.1)."""
    payload = {
        "outcome": "EVALUATING",
        "registry_check_passed": True,
        "tax_check_passed": True,
        "on_site_check_passed": True,
        "capacity_check_passed": True,
        "need_verification_points": 1,
        "valid_until": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_donation_product_payload(**overrides) -> dict:
    """Donation product family declaration (PRD §3.4)."""
    payload = {
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "product_kind": "ATHLETIC_SOCK",
        "design_channel": "DUAL_CHANNEL",
        "obligation_model": "AT_SALE",
        "approved_donation_ratio_units": 1,
        "retail_price_cents": DEFAULTS["RETAIL_PRICE_CENTS"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "is_reusable": True,
    }
    payload.update(overrides)
    return payload


def create_product_line_payload(**overrides) -> dict:
    """Sellable variant line under a donation product (PRD §3.4)."""
    payload = {
        "gtin": "00000000000001",
        "unit_size_label": "M",
        "is_essential_good": True,
        "donation_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_impact_season_payload(**overrides) -> dict:
    """Impact season calendar (PRD §3.7)."""
    payload = {
        "season_code": DEFAULTS["SEASON_CODE"],
        "starts_at": "2026-09-01T00:00:00Z",
        "ends_at": "2026-12-31T00:00:00Z",
        "freezes_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sales_order_payload(**overrides) -> dict:
    """Retail sales order (PRD §3.5)."""
    payload = {
        "order_number": "SO-FACTORY-1",
        "channel": "RETAIL_ECOM",
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(donation_product_line_id: str, **overrides) -> dict:
    """A purchased variant on an order; the obligation accrues immediately (PRD §3.5)."""
    payload = {
        "donation_product_line_id": donation_product_line_id,
        "quantity": DEFAULTS["QUANTITY"],
        "unit_price_cents": DEFAULTS["RETAIL_PRICE_CENTS"],
        "line_discount_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_return_request_payload(sales_order_line_id: str, **overrides) -> dict:
    """A return opened directly against a line id (PRD §3.6)."""
    payload = {
        "sales_order_line_id": sales_order_line_id,
        "request_reason": "SIZE",
        "requested_units": 1,
        "is_exchange": False,
        "expected_line_version": overrides.pop("expected_line_version", 1),
    }
    payload.update(overrides)
    return payload


def create_marketing_claim_payload(donation_product_id: str, partner_id: str, **overrides) -> dict:
    """A public donation claim for a product and a named partner (PRD §3.8)."""
    payload = {
        "donation_product_id": donation_product_id,
        "partner_id": partner_id,
        "stated_donation_units": DEFAULTS["STATED_UNITS"],
        "stated_ratio_text": "one purchased = one donated",
        "winback_multiplier": 1,
        "stated_reference_period": "SEASON",
    }
    payload.update(overrides)
    return payload


def create_allocation_commit_payload(
    giving_partner_id: str,
    claim_id: str,
    donation_product_id: str,
    expected_partner_version: int,
    **overrides,
) -> dict:
    """Commit one benefit allocation from a plan to a single partner (PRD §3.2)."""
    payload = {
        "giving_partner_id": giving_partner_id,
        "claim_id": claim_id,
        "donation_product_id": donation_product_id,
        "allocated_units": 10,
        "priority_tier": "CRITICAL",
        "liquidity_cap": 10,
        "expected_partner_version": expected_partner_version,
    }
    payload.update(overrides)
    return payload


def create_waterfall_allocation_payload(
    claim_id: str, donation_product_id: str, **overrides
) -> dict:
    """Spread a finite pool across every eligible partner at once (PRD §3.2)."""
    payload = {
        "claim_id": claim_id,
        "donation_product_id": donation_product_id,
        "liquidity_cap": 10,
        "baseline_units": 2400,
        "demand_units": 15000,
        "pool_units": 4000,
    }
    payload.update(overrides)
    return payload


def create_distribution_payload(**overrides) -> dict:
    """Ship units against an approved allocation (PRD §3.3)."""
    payload = {
        "shipped_units": 10,
        "shipment_reference": "TRK-FACTORY-1",
        "carrier_code": "UPS",
    }
    payload.update(overrides)
    return payload


def create_receipt_payload(**overrides) -> dict:
    """Confirm partner receipt, in whole or in part (PRD §3.3)."""
    payload = {
        "received_units": 10,
        "receipt_reference": "RCV-FACTORY-1",
    }
    payload.update(overrides)
    return payload


def create_impact_audit_payload(impact_season_id: str, claim_id: str, **overrides) -> dict:
    """Schedule an impact audit against a season and a claim (PRD §3.9)."""
    payload = {
        "impact_season_id": impact_season_id,
        "claim_id": claim_id,
        "audit_kind": "ANNUAL_IMPACT",
    }
    payload.update(overrides)
    return payload


def create_audit_finalize_payload(expected_audit_version: int, **overrides) -> dict:
    """Finalize an audit (PRD §3.9)."""
    payload = {
        "transaction_test_sample_size": 20,
        "transaction_test_exceptions": 0,
        "claimed_donation_units": 100,
        "expected_audit_version": expected_audit_version,
    }
    payload.update(overrides)
    return payload