"""Payload factories for every entity creation endpoint.

Only client-supplied (input) fields appear here; system and computed fields
are stamped server-side. Each factory returns a fresh dict so callers can
override any field without mutating shared state.
"""
from .constants import (
    HUB_NAME,
    HUB_TOTAL_HEADCOUNT,
    HUB_TONNAGE_BUDGET_CENTS,
    HUB_TRANSFER_CEILING_CENTS,
    SITE_KOT,
    REGION_NORTH,
    MARKET_RIVERTON,
    ROUTE_KOT_RIVERTON,
    CONTRACTOR_CEDAR,
    DELIVERY_ROUTE_R1,
    STOP_S1,
)


def create_hub_payload(**overrides) -> dict:
    payload = {
        "name": HUB_NAME,
        "total_newsroom_headcount": HUB_TOTAL_HEADCOUNT,
        "max_print_tonnage_budget_cents": HUB_TONNAGE_BUDGET_CENTS,
        "transfer_cost_ceiling_cents": HUB_TRANSFER_CEILING_CENTS,
    }
    payload.update(overrides)
    return payload


def create_print_site_payload(**overrides) -> dict:
    payload = dict(SITE_KOT)
    payload.update(overrides)
    return payload


def create_region_payload(**overrides) -> dict:
    payload = dict(REGION_NORTH)
    payload.update(overrides)
    return payload


def create_print_market_payload(**overrides) -> dict:
    payload = {
        "name": MARKET_RIVERTON["name"],
        "per_copy_revenue_cents": MARKET_RIVERTON["per_copy_revenue_cents"],
        "daily_route_cost_ceiling_cents": MARKET_RIVERTON["daily_route_cost_ceiling_cents"],
        "weighted_demand_units": MARKET_RIVERTON["weighted_demand_units"],
        "print_edition_per_week": MARKET_RIVERTON["print_edition_per_week"],
    }
    payload.update(overrides)
    return payload


def create_print_route_payload(destination_market_id: str, **overrides) -> dict:
    payload = {
        "destination_market_id": destination_market_id,
        "transit_minutes": ROUTE_KOT_RIVERTON["transit_minutes"],
        "dispatch_cutoff_utc": ROUTE_KOT_RIVERTON["dispatch_cutoff_utc"],
        "is_direct_hop": ROUTE_KOT_RIVERTON["is_direct_hop"],
        "buffer_minutes": ROUTE_KOT_RIVERTON["buffer_minutes"],
    }
    payload.update(overrides)
    return payload


def create_edition_payload(assigned_print_site_id: str, **overrides) -> dict:
    payload = {
        "assigned_print_site_id": assigned_print_site_id,
        "slug": "2026-09-21",
        "page_count": 12,
        "requested_print_run_copies": 40000,
        "late_sports_engineering_flag": False,
        "legal_notice_count": 0,
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> dict:
    payload = dict(CONTRACTOR_CEDAR)
    payload.update(overrides)
    return payload


def create_delivery_route_payload(print_market_id: str, **overrides) -> dict:
    payload = {"print_market_id": print_market_id}
    payload.update(DELIVERY_ROUTE_R1)
    payload.update(overrides)
    return payload


def create_delivery_stop_payload(print_market_id: str, **overrides) -> dict:
    payload = {"print_market_id": print_market_id}
    payload.update(STOP_S1)
    payload.update(overrides)
    return payload


def create_subscriber_payload(**overrides) -> dict:
    payload = {
        "subscriber_ref": "SUB-001",
        "remaining_print_issues": 40,
        "paid_through_utc": "2027-06-01T00:00:00Z",
        "print_issue_value_cents": 1200,
    }
    payload.update(overrides)
    return payload


def create_retention_action_payload(**overrides) -> dict:
    payload = {
        "retention_offer_code": "CREDIT30",
        "retention_credit_cents": 3000,
        "eligibility_policy_id": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_newsroom_position_payload(**overrides) -> dict:
    payload = {
        "role_code": "REPORTER",
        "expertise_code": "HIGH_SCHOOL_SPORTS",
        "monthly_cost_cents": 520000,
    }
    payload.update(overrides)
    return payload


def create_newsroom_change_payload(newsroom_position_id: str, to_region_id: str,
                                   from_region_id: str, expected_hub_version: int,
                                   **overrides) -> dict:
    payload = {
        "newsroom_position_id": newsroom_position_id,
        "to_region_id": to_region_id,
        "from_region_id": from_region_id,
        "effective_date": "2026-09-11",
        "layoff_order_index": 1,
        "requested_slots": 40,
        "expected_hub_version": expected_hub_version,
    }
    payload.update(overrides)
    return payload


def create_title_closure_payload(**overrides) -> dict:
    payload = {
        "title_code": "RIV-HERALD",
        "archive_retention_years": 25,
        "digital_replacement_url": "https://example.test/riverton-digital",
    }
    payload.update(overrides)
    return payload


def print_volume_payload(print_site_id: str, day: str, charge_cents: int) -> dict:
    return {"print_site_id": print_site_id, "day": day, "charge_cents": charge_cents}


def plan_transfer_payload(receiving_print_site_id: str, expected_hub_version: int) -> dict:
    return {
        "receiving_print_site_id": receiving_print_site_id,
        "expected_hub_version": expected_hub_version,
    }