"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import WEEK_END, WEEK_START


def create_market_payload(**overrides) -> dict:
    defaults = {
        "market_code": "TST",
        "geo_cells": ["cellA"],
        "incentive_budget_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "display_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def _program_base(market_id: str, program_type: str, title: str) -> dict:
    return {
        "market_id": market_id,
        "program_type": program_type,
        "title": title,
        "window_start_utc": WEEK_START,
        "window_end_utc": WEEK_END,
        "stacking_class": "STACKABLE",
        "excluded_ride_types": [],
    }


def create_streak_program_payload(market_id: str, **overrides) -> dict:
    defaults = _program_base(market_id, "STREAK", "Streak Program")
    defaults.update({"streak_length": 2, "streak_payout_cents": 5000})
    defaults.update(overrides)
    return defaults


def create_zone_program_payload(market_id: str, **overrides) -> dict:
    defaults = _program_base(market_id, "BONUS_ZONE", "Zone Program")
    defaults.update(
        {"geo_cell_id": "cellA", "zone_multiplier_bps": 15000, "capacity": 10}
    )
    defaults.update(overrides)
    return defaults


def create_challenge_program_payload(market_id: str, **overrides) -> dict:
    defaults = _program_base(market_id, "CHALLENGE", "Challenge Program")
    defaults.update({"challenge_ride_target": 2, "challenge_payout_cents": 12000})
    defaults.update(overrides)
    return defaults


def create_guarantee_program_payload(market_id: str, **overrides) -> dict:
    defaults = _program_base(market_id, "GUARANTEE", "Guarantee Program")
    defaults.update({"guaranteed_weekly_cents": 500000, "guaranteed_min_rides": 1})
    defaults.update(overrides)
    return defaults


def create_ride_payload(driver_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "market_id": market_id,
        "ride_type": "STANDARD",
        "geo_cell_id": "cellA",
        "base_fare_cents": 10000,
        "tips_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def enroll_payload(driver_id: str) -> dict:
    return {"driver_id": driver_id}


def rate_events_payload(accepted: int, declined: int = 0, driver_cancelled: int = 0) -> dict:
    """Build a batch of dispatch rate events (PRD §3.2)."""
    events = (
        [{"type": "OFFER_ACCEPTED"}] * accepted
        + [{"type": "OFFER_DECLINED"}] * declined
        + [{"type": "DRIVER_CANCEL"}] * driver_cancelled
    )
    return {"events": events}


def create_fraud_flag_payload(
    driver_id: str, ride_id: str, signal_type: str = "INFLATED_RIDE",
    severity: int = 5, **overrides,
) -> dict:
    defaults = {
        "driver_id": driver_id,
        "ride_id": ride_id,
        "signal_type": signal_type,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def compute_settlement_payload(driver_id: str, program_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "program_id": program_id,
        "week_start_utc": WEEK_START,
    }
    defaults.update(overrides)
    return defaults


def compute_statement_payload(driver_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "week_start_utc": WEEK_START,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(driver_id: str, subject_type: str = "ELIGIBILITY", **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "subject_type": subject_type,
        "reason": "test appeal",
    }
    defaults.update(overrides)
    return defaults


def create_forecast_payload(**overrides) -> dict:
    defaults = {
        "baseline_rides": 1000,
        "lift_bps": 1000,
        "cannibalization_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_supply_shortfall_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "geo_cell_id": "cellA",
        "hour_bucket": 17,
        "severity_bps": 5000,
    }
    defaults.update(overrides)
    return defaults
