"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Agent A",
        "license_number": "LIC-001",
        "brokerage": "Brokerage X",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Vendor V",
        "trade": "GENERAL",
    }
    defaults.update(overrides)
    return defaults


def create_capacity_window_payload(**overrides) -> dict:
    defaults = {
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
        "capacity_crew_days": TEST_DEFAULTS["CAPACITY_CREW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "address_line": TEST_DEFAULTS["ADDRESS_LINE"],
        "estimated_property_value_cents": TEST_DEFAULTS["ESTIMATED_PROPERTY_VALUE_CENTS"],
        "expected_sale_proceeds_cents": TEST_DEFAULTS["EXPECTED_SALE_PROCEEDS_CENTS"],
        "listing_agreement_signed": True,
        "listing_agreement_disclosure_ack": True,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "title": TEST_DEFAULTS["PROJECT_TITLE"],
        "recommended_by_agent": True,
        "expected_sale_price_lift_cents": TEST_DEFAULTS["PROJECT_LIFT_CENTS"],
        "estimated_cost_cents": TEST_DEFAULTS["PROJECT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "agreed_price_cents": TEST_DEFAULTS["AGREED_PRICE_CENTS"],
        "start_date": TEST_DEFAULTS["ENGAGEMENT_START"],
        "end_date": TEST_DEFAULTS["ENGAGEMENT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": TEST_DEFAULTS["DISBURSEMENT_AMOUNT_CENTS"],
        "kind": "DEPOSIT",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "delta_cents": 100_000,
        "reason": "SCOPE_CREEP",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "dispute_kind": "WORKMANSHIP",
        "claimed_amount_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_listing_event_payload(**overrides) -> dict:
    defaults = {
        "event_kind": "LISTED",
        "event_at": "2026-09-10T00:00:00Z",
        "price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(**overrides) -> dict:
    defaults = {"resolution": "RESOLVED_VENDOR_FAULT"}
    defaults.update(overrides)
    return defaults
