"""Entity representations. Computed fields are evaluated at read time."""

import calc

COMMON = ("id", "created_at", "updated_at", "version")

MARKET_FIELDS = (
    "code", "name", "region", "transport_hub_distance_km",
    "transfer_cost_per_km_cents", "storage_cost_per_day_cents",
    "prep_capacity_per_day", "registration_lead_days", "status",
)
SEGMENT_FIELDS = (
    "code", "name", "baseline_daily_rate_cents", "target_utilization_pct",
    "target_revenue_per_unit_month_cents", "mileage_band_soft_limit_km",
    "mileage_band_hard_limit_km", "recondition_cap_cents",
)
PROGRAM_FIELDS = (
    "manufacturer_name", "program_year", "program_type", "repurchase_guarantee_pct",
    "min_holding_days", "max_holding_days", "max_eligible_mileage_km",
    "excess_mileage_charge_cents_per_km", "damage_deduction_cap_cents", "status",
)
CHANNEL_FIELDS = (
    "code", "name", "fee_pct", "fixed_fee_cents", "expected_days_to_sell",
    "expected_proceeds_multiplier", "recondition_required", "status",
)
POLICY_FIELDS = (
    "segment_id", "supersedes_policy_id", "name", "monthly_depreciation_pct",
    "mileage_depreciation_cents_per_km", "floor_residual_pct", "effective_from",
    "created_by_user_id", "activated_by_user_id", "status",
)
PLAN_FIELDS = (
    "market_id", "season", "plan_year", "planned_unit_count",
    "revenue_per_unit_target_cents", "utilization_target_pct", "status",
)
ALLOCATION_FIELDS = (
    "plan_id", "program_id", "segment_id", "unit_count",
    "capitalized_cost_per_unit_cents", "status",
)
VEHICLE_FIELDS = (
    "allocation_id", "segment_id", "program_id", "current_market_id", "vin",
    "capitalized_cost_cents", "fleet_status", "condition_status", "odometer_km",
    "rented_days_total", "available_days_total", "revenue_to_date_cents",
    "registered_at", "licensed_at", "prep_completed_at", "first_rent_ready_at",
    "in_service_at", "held_for_sale_at", "net_book_value_at_hold_cents",
)
TASK_FIELDS = (
    "vehicle_id", "market_id", "task_type", "cost_cents", "bay_code",
    "window_start", "window_end", "completed_at", "status",
)
ORDER_FIELDS = (
    "vehicle_id", "origin_market_id", "destination_market_id", "distance_km",
    "planned_depart_at", "planned_receive_at", "proposed_by_user_id",
    "authorized_by_user_id", "revision_count", "rejection_reason",
    "estimated_transport_cost_cents", "actual_transport_cost_cents",
    "depart_at", "receive_at", "status",
)
DAMAGE_FIELDS = (
    "vehicle_id", "market_id", "damage_type", "estimate_cents",
    "net_book_value_at_report_cents", "total_loss_required", "recovery_source",
    "recovered_cents", "recovery_alloc_recondition_cents",
    "recovery_alloc_depreciation_cents", "recovery_alloc_income_cents",
    "salvage_proceeds_cents", "total_loss_gain_loss_cents", "status",
)
CONSIGNMENT_FIELDS = (
    "vehicle_id", "channel_id", "created_by_user_id", "settled_by_user_id",
    "floor_price_cents", "recondition_authorized_cents", "recondition_actual_cents",
    "recondition_loaded_cents", "gross_proceeds_cents", "channel_fee_cents",
    "transport_to_channel_cents", "net_proceeds_cents", "gain_loss_cents",
    "listed_at", "settled_at", "status",
)
LEDGER_FIELDS = (
    "vehicle_id", "entry_type", "amount_cents", "source_entity_type",
    "source_entity_id", "posted_at", "memo",
)


def _pick(row, fields, common=COMMON):
    out = {}
    for name in common:
        out[name] = row.get(name)
    for name in fields:
        out[name] = row.get(name)
    return out


def market(row):
    data = _pick(row, MARKET_FIELDS)
    data["in_service_unit_count"] = calc.market_census(row["id"])
    return data


def segment(row):
    return _pick(row, SEGMENT_FIELDS)


def program(row):
    return _pick(row, PROGRAM_FIELDS)


def channel(row):
    return _pick(row, CHANNEL_FIELDS)


def policy(row):
    return _pick(row, POLICY_FIELDS)


def plan(row):
    data = _pick(row, PLAN_FIELDS)
    allocated = calc.plan_allocated_unit_count(row)
    data["allocated_unit_count"] = allocated
    data["in_fleeted_unit_count"] = calc.plan_in_fleeted_unit_count(row)
    data["posture"] = calc.plan_posture(row, allocated)
    return data


def allocation(row):
    data = _pick(row, ALLOCATION_FIELDS)
    data["in_fleeted_count"] = calc.allocation_in_fleeted_count(row)
    data["created_vehicle_count"] = calc.allocation_created_vehicle_count(row)
    return data


def vehicle(row):
    data = _pick(row, VEHICLE_FIELDS)
    data["total_recondition_cents"] = calc.total_recondition_cents(row)
    data["net_book_value_cents"] = calc.net_book_value(row)
    return data


def task(row):
    return _pick(row, TASK_FIELDS)


def order(row):
    return _pick(row, ORDER_FIELDS)


def damage_event(row):
    return _pick(row, DAMAGE_FIELDS)


def consignment(row):
    return _pick(row, CONSIGNMENT_FIELDS)


def ledger_entry(row):
    return _pick(row, LEDGER_FIELDS, common=("id", "created_at"))
