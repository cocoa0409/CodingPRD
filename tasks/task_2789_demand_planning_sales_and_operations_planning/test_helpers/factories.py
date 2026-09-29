"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import PLANNER_USER_ID, TEST_DEFAULTS


def product_family_payload(**overrides) -> dict:
    payload = {
        "family_code": "FAM-BASE",
        "name": "Base Family",
        "accountable_planner_user_id": PLANNER_USER_ID,
        "units_per_hour": TEST_DEFAULTS["FAMILY_UNITS_PER_HOUR"],
        "max_monthly_hours": TEST_DEFAULTS["FAMILY_MAX_MONTHLY_HOURS"],
    }
    payload.update(overrides)
    return payload


def item_payload(family_id: str, **overrides) -> dict:
    """Item create payload. ``service_level_target_pct``, ``demand_cv``,
    ``lead_time_days``, ``npi_ramp_pct`` and ``lifecycle_state`` are optional and
    are only sent when the caller overrides them."""
    payload = {
        "sku": "SKU-BASE",
        "family_id": family_id,
        "unit_price_cents": TEST_DEFAULTS["ITEM_UNIT_PRICE_CENTS"],
        "unit_cost_cents": TEST_DEFAULTS["ITEM_UNIT_COST_CENTS"],
        "on_hand_units": 0,
        "material_supply_cap_units": TEST_DEFAULTS["ITEM_MATERIAL_SUPPLY_CAP_UNITS"],
        "avg_monthly_demand_units": TEST_DEFAULTS["ITEM_AVG_MONTHLY_DEMAND_UNITS"],
    }
    payload.update(overrides)
    return payload


def mature_item_payload(family_id: str, **overrides) -> dict:
    """The recurring item shape: MATURE with the 95.0 / 0.20 / 30 policy triple
    supplied explicitly, which yields safety_stock_units 330."""
    payload = item_payload(
        family_id,
        service_level_target_pct=95.0,
        demand_cv=0.20,
        lead_time_days=30,
        lifecycle_state="MATURE",
    )
    payload.update(overrides)
    return payload


def customer_payload(**overrides) -> dict:
    payload = {
        "customer_code": "CUST-BASE",
        "name": "Base Grocery",
        "channel": "GROCERY",
        "priority_rank": TEST_DEFAULTS["CUSTOMER_PRIORITY_RANK"],
    }
    payload.update(overrides)
    return payload


def capacity_block_payload(family_id: str, **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "available_hours": 9,
    }
    payload.update(overrides)
    return payload


def promotion_payload(item_id: str, customer_id: str, **overrides) -> dict:
    payload = {
        "item_id": item_id,
        "customer_id": customer_id,
        "start_month": "2026-10",
        "end_month": "2026-10",
        "lift_pct": 10,
        "cannibalization_pct": 0,
    }
    payload.update(overrides)
    return payload


def planning_cycle_payload(**overrides) -> dict:
    payload = {
        "cycle_code": "CY-BASE",
        "horizon_start_month": TEST_DEFAULTS["HORIZON_MONTH"],
        "horizon_end_month": TEST_DEFAULTS["HORIZON_MONTH"],
        "financial_commitment_cents": 0,
        "supply_review_policy": "NET_INVENTORY_FIRST",
    }
    payload.update(overrides)
    return payload


def demand_forecast_payload(
    cycle_id: str, item_id: str, customer_id: str, **overrides
) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "item_id": item_id,
        "customer_id": customer_id,
        "month": TEST_DEFAULTS["HORIZON_MONTH"],
        "level_units": 1000,
        "trend_units_per_month": 0,
        "seasonal_index": 1.0,
        "causal_uplift_pct": 0,
    }
    payload.update(overrides)
    return payload


def consensus_adjustment_payload(
    demand_forecast_id: str,
    expected_demand_forecast_version: int,
    adjustment_type: str = "SALES_INTELLIGENCE",
    delta_units: int = 0,
    **overrides,
) -> dict:
    payload = {
        "demand_forecast_id": demand_forecast_id,
        "adjustment_type": adjustment_type,
        "delta_units": delta_units,
        "rationale": "sales intelligence from the field",
        "expected_demand_forecast_version": expected_demand_forecast_version,
    }
    payload.update(overrides)
    return payload


def adjustment_review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def adjustment_resubmit_payload(
    expected_demand_forecast_version: int, **overrides
) -> dict:
    payload = {
        "rationale": "revised after review",
        "expected_demand_forecast_version": expected_demand_forecast_version,
    }
    payload.update(overrides)
    return payload


def supply_plan_payload(cycle_id: str, item_id: str, **overrides) -> dict:
    payload = {"cycle_id": cycle_id, "item_id": item_id}
    payload.update(overrides)
    return payload


def capacity_investment_scenario_payload(
    cycle_id: str, target_item_id: str, added_capacity_hours, **overrides
) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "scenario_type": "CAPACITY_INVESTMENT",
        "name": "Second shift",
        "target_item_id": target_item_id,
        "added_capacity_hours": added_capacity_hours,
    }
    payload.update(overrides)
    return payload


def price_realization_scenario_payload(
    cycle_id: str, price_increase_pct, **overrides
) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "scenario_type": "PRICE_REALIZATION",
        "name": "List price realisation",
        "price_increase_pct": price_increase_pct,
    }
    payload.update(overrides)
    return payload


def accuracy_record_payload(
    cycle_id: str, item_id: str, customer_id: str, actual_units: int, **overrides
) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "item_id": item_id,
        "customer_id": customer_id,
        "actual_units": actual_units,
    }
    payload.update(overrides)
    return payload


def inventory_policy_payload(
    service_level_target_pct, demand_cv, lead_time_days, **overrides
) -> dict:
    payload = {
        "service_level_target_pct": service_level_target_pct,
        "demand_cv": demand_cv,
        "lead_time_days": lead_time_days,
    }
    payload.update(overrides)
    return payload


def item_lifecycle_payload(target_state: str, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def cycle_transition_payload(target_status: str, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def forecast_transition_payload(target_status: str, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def scenario_select_payload(expected_cycle_version: int, **overrides) -> dict:
    payload = {"expected_cycle_version": expected_cycle_version}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
