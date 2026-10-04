"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_region_payload(**overrides) -> dict:
    defaults = {"code": "REG-1", "name": "Region One"}
    defaults.update(overrides)
    return defaults


def create_dealer_payload(region_id, **overrides) -> dict:
    defaults = {
        "region_id": region_id,
        "dealer_code": "D-0001",
        "name": "Test Dealer",
        "opened_on": TEST_DEFAULTS["OLD_OPENED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_model_line_payload(**overrides) -> dict:
    defaults = {"model_code": "L-1", "name": "Test Line"}
    defaults.update(overrides)
    return defaults


def create_commodity_payload(**overrides) -> dict:
    defaults = {"code": "FEAT-1", "name": "Feature One"}
    defaults.update(overrides)
    return defaults


def create_commodity_restriction_payload(commodity_id, model_line_id, **overrides) -> dict:
    defaults = {
        "commodity_id": commodity_id,
        "model_line_id": model_line_id,
        "effective_from": TEST_DEFAULTS["RESTRICTION_FROM"],
        "effective_to": None,
        "install_rate_pct": 50,
        "allow_partial_build": True,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_run_payload(model_line_id, **overrides) -> dict:
    defaults = {
        "period": "2026-09",
        "model_line_id": model_line_id,
        "base_units": 10,
        "lookback_start": TEST_DEFAULTS["LOOKBACK_START"],
        "lookback_end": TEST_DEFAULTS["LOOKBACK_END"],
        "retail_priority_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(dealer_id, model_line_id, run_id, expected_version, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "model_line_id": model_line_id,
        "run_id": run_id,
        "order_kind": "STOCK",
        "expected_dealer_allocation_version": expected_version,
        "configuration": {"trim": TEST_DEFAULTS["TRIM"], "commodity_codes": []},
    }
    defaults.update(overrides)
    return defaults


def create_dealer_trade_payload(from_dealer_id, to_dealer_id, run_id, **overrides) -> dict:
    defaults = {
        "from_dealer_id": from_dealer_id,
        "to_dealer_id": to_dealer_id,
        "run_id": run_id,
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(dealer_id, run_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "run_id": run_id,
        "appeal_type": "MARKET_GAP",
        "requested_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_incentive_program_payload(model_line_id, **overrides) -> dict:
    defaults = {
        "code": "PROG-1",
        "model_line_id": model_line_id,
        "kind": "VOLUME_BONUS",
        "params": {
            "tier1_threshold": 3,
            "tier1_bonus_cents": 500,
            "tier2_threshold": 5,
            "tier2_bonus_cents": 900,
        },
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {"code": "CAR-1", "name": "Carrier One", "weekly_capacity": 5}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id, carrier_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "carrier_id": carrier_id,
        "pickup_week": TEST_DEFAULTS["BUILD_WEEK"],
    }
    defaults.update(overrides)
    return defaults


def seed_order_at_week_payload(dealer_id, model_line_id, run_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "model_line_id": model_line_id,
        "run_id": run_id,
        "order_kind": "STOCK",
        "scheduled_week": "2026-W30",
    }
    defaults.update(overrides)
    return defaults
