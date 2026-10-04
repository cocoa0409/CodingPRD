"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _suffix() -> int:
    return next(_counter)


def create_season_payload(**overrides) -> dict:
    defaults = {
        "season_code": f"{TEST_DEFAULTS['SEASON_CODE']}-{_suffix()}",
        "start_date": TEST_DEFAULTS["SEASON_START"],
        "end_date": TEST_DEFAULTS["SEASON_END"],
        "department_otb_budget_cents": TEST_DEFAULTS["SEASON_BUDGET"],
        "packaway_reserve_ratio": TEST_DEFAULTS["SEASON_RESERVE_RATIO"],
    }
    defaults.update(overrides)
    return defaults


def create_target_season_payload(**overrides) -> dict:
    defaults = {
        "season_code": f"{TEST_DEFAULTS['TARGET_SEASON_CODE']}-{_suffix()}",
        "start_date": TEST_DEFAULTS["TARGET_SEASON_START"],
        "end_date": TEST_DEFAULTS["TARGET_SEASON_END"],
        "department_otb_budget_cents": TEST_DEFAULTS["TARGET_SEASON_BUDGET"],
        "packaway_reserve_ratio": TEST_DEFAULTS["TARGET_SEASON_RESERVE_RATIO"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    n = _suffix()
    defaults = {
        "legal_name": f"Vendor {n} Trading Co",
        "vendor_code": f"V{n}",
        "discretion_level": "STANDARD",
        "ticket_discretion_required": False,
        "default_zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "vendor_tier": "A",
    }
    defaults.update(overrides)
    return defaults


def create_price_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "compare_at_multiplier": TEST_DEFAULTS["COMPARE_AT_MULTIPLIER"],
        "markdown_cadence_weeks": TEST_DEFAULTS["MARKDOWN_CADENCE_WEEKS"],
        "clearance_weeks": TEST_DEFAULTS["CLEARANCE_WEEKS"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(vendor_id: str, season_id: str, **overrides) -> dict:
    defaults = {
        "lot_code": f"LOT-{_suffix()}",
        "vendor_id": vendor_id,
        "season_id": season_id,
        "lot_type": "CLOSEOUT",
        "disposition": "IMMEDIATE",
        "asking_price_cents": 1_000_000,
        "mixed_lot": False,
        "unit_count": 100,
        "expected_sell_through_pct": 0.9,
        "estimated_unit_retail_cents": 5_000,
        "offer_expires_at": TEST_DEFAULTS["OFFER_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_line_payload(**overrides) -> dict:
    defaults = {
        "style_code": f"STYLE-{_suffix()}",
        "department": "APPAREL",
        "quantity": 100,
        "unit_cost_cents": 11_500,
        "compare_at_claim_cents": 15_000,
        "target_retail_cents": 5_000,
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "warehouse_code": f"W-{_suffix()}",
        "pallet_capacity": 200,
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "monthly_holding_rate_per_pallet_cents": TEST_DEFAULTS["WAREHOUSE_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_packaway_hold_payload(lot_id: str, warehouse_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "warehouse_id": warehouse_id,
        "pallet_count": 2,
        "release_window_start": TEST_DEFAULTS["RELEASE_WINDOW_START"],
        "release_window_end": TEST_DEFAULTS["RELEASE_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_code": f"ST-{_suffix()}",
        "cluster_code": "SUBURBAN_FAMILY",
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "storage_capacity_units": 500,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_plan_payload(lot_id: str, season_id: str, expected_lot_version: int, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "season_id": season_id,
        "total_units": 100,
        "cluster_weights": {"SUBURBAN_FAMILY": 1.0},
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_store_sku_payload(store_id: str, lot_line_id: str, ticket_id: str, season_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "lot_line_id": lot_line_id,
        "ticket_id": ticket_id,
        "season_id": season_id,
        "units_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(lot_line_id: str, **overrides) -> dict:
    defaults = {
        "lot_line_id": lot_line_id,
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(lot_id: str, warehouse_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "warehouse_id": warehouse_id,
    }
    defaults.update(overrides)
    return defaults


def create_shrink_case_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "shrink_type": "DAMAGE",
        "units_lost": 0,
        "units_untraceable": 1,
    }
    defaults.update(overrides)
    return defaults


def create_liquidation_order_payload(store_id: str, lot_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "lot_id": lot_id,
        "reason": "CLEARANCE_WEEKS_EXCEEDED",
        "recovery_rate_pct": 0.5,
    }
    defaults.update(overrides)
    return defaults
