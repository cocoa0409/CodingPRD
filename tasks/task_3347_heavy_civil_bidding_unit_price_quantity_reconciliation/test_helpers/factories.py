"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    DEFAULT_BID_DEADLINE_AT,
    DEFAULT_CONTRACT_TYPE,
    DEFAULT_MAINTAIN_BOND_HORIZON_DAYS,
    DEFAULT_MEASURED_AT,
    DEFAULT_RETENTION_RATE_PCT,
    BOND_EFFECTIVE_FROM,
    BOND_EFFECTIVE_TO,
    CREW_DAY_EQUIPMENT_CENTS,
    CREW_DAY_LABOR_CENTS,
    DAILY_PRODUCTIVITY_UNITS,
    OVERRUN_THRESHOLD_PCT,
    QUOTE_WINDOW_END,
    QUOTE_WINDOW_START,
    SURETY_AGGREGATE_CAPACITY_CENTS,
    SURETY_NAME,
    SURETY_SINGLE_JOB_LIMIT_CENTS,
    UNDERRUN_THRESHOLD_PCT,
)


def project_payload(**overrides) -> dict:
    payload = {
        "project_code": "CALTRANS-04-1J5604",
        "owner_agency_name": "Caltrans District 4",
        "contract_type": DEFAULT_CONTRACT_TYPE,
        "bid_deadline_at": DEFAULT_BID_DEADLINE_AT,
        "retention_rate_pct": DEFAULT_RETENTION_RATE_PCT,
        "advertised_dbe_goal_pct": DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    }
    payload.update(overrides)
    return payload


def surety_payload(**overrides) -> dict:
    payload = {
        "surety_name": SURETY_NAME,
        "aggregate_capacity_cents": SURETY_AGGREGATE_CAPACITY_CENTS,
        "single_job_limit_cents": SURETY_SINGLE_JOB_LIMIT_CENTS,
    }
    payload.update(overrides)
    return payload


def bid_item_payload(**overrides) -> dict:
    payload = {
        "item_code": "2025-390102",
        "item_description": "Class 2 aggregate base",
        "unit_of_measure": "TON",
        "estimated_quantity": 1000,
        "overrun_threshold_pct": OVERRUN_THRESHOLD_PCT,
        "underrun_threshold_pct": UNDERRUN_THRESHOLD_PCT,
    }
    payload.update(overrides)
    return payload


def pricing_payload(**overrides) -> dict:
    payload = {
        "bid_unit_price_cents": 3000,
        "crew_day_labor_cents": CREW_DAY_LABOR_CENTS,
        "crew_day_equipment_cents": CREW_DAY_EQUIPMENT_CENTS,
        "daily_productivity_units": DAILY_PRODUCTIVITY_UNITS,
    }
    payload.update(overrides)
    return payload


def quote_payload(**overrides) -> dict:
    payload = {
        "trade_code": "SWPPP",
        "contact_name": "Dana Reyes",
        "quoted_amount_cents": 18_000_000,
        "quote_window_start": QUOTE_WINDOW_START,
        "quote_window_end": QUOTE_WINDOW_END,
        "unicap_registered": True,
        "good_faith_effort_basis": "SOLICITED_DBE",
    }
    payload.update(overrides)
    return payload


def bond_payload(**overrides) -> dict:
    payload = {
        "bond_type": "PERFORMANCE",
        "bond_amount_cents": 12_000_000,
        "effective_from": BOND_EFFECTIVE_FROM,
        "effective_to": BOND_EFFECTIVE_TO,
        "maintain_bond_horizon_days": DEFAULT_MAINTAIN_BOND_HORIZON_DAYS,
    }
    payload.update(overrides)
    return payload


def measurement_payload(**overrides) -> dict:
    payload = {
        "measured_quantity": 1000,
        "measured_at": DEFAULT_MEASURED_AT,
    }
    payload.update(overrides)
    return payload


def condition_payload(**overrides) -> dict:
    payload = {
        "reported_at": "2026-12-03T00:00:00Z",
        "claimed_amount_cents": 3_000_000,
    }
    payload.update(overrides)
    return payload


def commitment_payload(**overrides) -> dict:
    payload = {"committed_amount_cents": 12_000_000}
    payload.update(overrides)
    return payload
