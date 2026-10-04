"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_tour_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Tour",
        "home_base_city": "Tampa",
        "season_start_on": TEST_DEFAULTS["SEASON_START"],
        "season_end_on": TEST_DEFAULTS["SEASON_END"],
        "market_cooldown_days": TEST_DEFAULTS["MARKET_COOLDOWN_DAYS"],
        "royalty_reserve_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Arena",
        "market_code": "DAL",
        "capacity_seats": 10000,
        "load_in_dock_doors": 4,
        "union_rule_set": "NON_UNION",
        "default_rent_cents": TEST_DEFAULTS["DEFAULT_RENT_CENTS"],
        "percentage_share_pct": TEST_DEFAULTS["PERCENTAGE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_rigging_point_payload(**overrides) -> dict:
    defaults = {
        "label": "Grid A-1",
        "zone": "GRID",
        "max_static_load_kg": 5000,
        "max_dynamic_load_kg": 500,
    }
    defaults.update(overrides)
    return defaults


def create_date_avail_payload(**overrides) -> dict:
    defaults = {
        "opens_at": TEST_DEFAULTS["AVAIL_OPENS"],
        "closes_at": TEST_DEFAULTS["AVAIL_CLOSES"],
        "priority_rank": 10,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(venue_id, date_avail_id, expected_avail_version, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "date_avail_id": date_avail_id,
        "load_in_at": TEST_DEFAULTS["LOAD_IN"],
        "first_show_at": TEST_DEFAULTS["FIRST_SHOW"],
        "load_out_at": TEST_DEFAULTS["LOAD_OUT"],
        "deal_type": "FLAT_RENT",
        "agreed_rent_cents": TEST_DEFAULTS["DEFAULT_RENT_CENTS"],
        "expected_avail_version": expected_avail_version,
    }
    defaults.update(overrides)
    return defaults


def create_rigging_allocation_payload(rigging_point_id, **overrides) -> dict:
    defaults = {
        "rigging_point_id": rigging_point_id,
        "static_load_kg": 1000,
        "dynamic_load_kg": 0,
        "purpose": "aerial rig",
    }
    defaults.update(overrides)
    return defaults


def create_labor_call_payload(**overrides) -> dict:
    defaults = {
        "department": "RIGGERS",
        "headcount": 2,
        "call_start_at": "2026-09-10T08:00:00Z",
        "call_end_at": "2026-09-10T18:00:00Z",
        "hourly_rate_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_truck_move_payload(**overrides) -> dict:
    defaults = {
        "cargo_kind": "VEHICLES",
        "truck_count": 4,
        "arrival_at": "2026-09-10T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_scale_payload(**overrides) -> dict:
    defaults = {
        "tier_label": "GOLD",
        "base_price_cents": 10000,
        "seats_allocated": 2000,
        "tier_rank": 1,
        "on_sale_at": TEST_DEFAULTS["ON_SALE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_ticket_sale_payload(ticket_scale_id, quantity, **overrides) -> dict:
    defaults = {"ticket_scale_id": ticket_scale_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(**overrides) -> dict:
    defaults = {
        "property_code": "DINO",
        "licensor_name": "Dino IP LLC",
        "royalty_pct": 0.08,
        "starts_on": TEST_DEFAULTS["SEASON_START"],
        "ends_on": TEST_DEFAULTS["SEASON_END"],
    }
    defaults.update(overrides)
    return defaults


def create_safety_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_kind": "RIGGING",
        "scheduled_at": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults
