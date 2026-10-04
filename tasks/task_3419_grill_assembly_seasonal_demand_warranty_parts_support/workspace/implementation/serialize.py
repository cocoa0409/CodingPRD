"""Serializers: whitelist the public fields per entity (drops internal _seq).
Clock-dependent derived fields are refreshed lazily on read (PRD §2.4)."""

import derive

COMMON = ("id", "created_at", "updated_at", "version")

SEASON_FIELDS = COMMON + (
    "name", "year", "build_start", "allocation_open", "in_season_start",
    "clearance_start", "season_end", "demand_forecast_units", "status",
)
MODEL_FIELDS = COMMON + (
    "model_code", "model_family", "model_year", "base_price_cents",
    "demand_share_bp", "burner_coverage_years", "grate_coverage_years",
    "electronics_coverage_years", "other_coverage_years", "parts_support_years",
    "current_firmware_version", "status", "discontinued_at",
    "support_obligation_until",
)
CHANNEL_FIELDS = COMMON + (
    "name", "channel_type", "service_tier", "allocation_priority",
    "credit_limit_cents", "subsidy_bp", "outstanding_exposure_cents",
    "accessory_attach_rate", "fuel_attach_rate",
)
LOT_FIELDS = COMMON + (
    "season_id", "model_id", "build_week", "units_built", "units_available",
    "units_consumed", "recommended_build_forward_units",
    "recommended_build_actual_units", "status",
)
ALLOCATION_FIELDS = COMMON + (
    "season_id", "channel_account_id", "model_id", "allocated_units",
    "committed_units", "status", "offered_at",
)
ASSEMBLER_FIELDS = COMMON + (
    "name", "certification_level", "service_regions", "max_concurrent_jobs",
    "status", "active_job_count", "jobs_completed", "no_show_count",
    "no_show_history", "completion_history", "official_quality_bp",
    "provisional_quality_bp",
)
JOB_FIELDS = COMMON + (
    "sale_id", "assembler_id", "job_type", "distance_mi", "window_start",
    "window_end", "fee_cents", "status",
)
SALE_FIELDS = COMMON + (
    "season_id", "model_id", "channel_account_id", "quantity", "serials",
    "accessories", "accessory_count", "has_cover", "has_tools", "has_fuel",
    "unit_price_cents", "proof_of_purchase_token", "status", "sold_at",
    "registered_at",
)
CLAIM_FIELDS = COMMON + (
    "sale_id", "component", "failure_description", "serial_number",
    "claim_date", "coverage_determination", "goodwill",
    "provisional_settlement_cents", "final_settlement_cents",
    "settlement_delta_cents", "settlement_parts_order_id", "denied_at",
    "status",
)
PART_FIELDS = COMMON + (
    "part_number", "component", "compatible_model_codes",
    "supersession_chain_id", "chain_position", "unit_cost_cents",
    "stock_quantity", "status",
)
PARTS_ORDER_FIELDS = COMMON + (
    "part_id", "sale_id", "warranty_claim_id", "fulfillment_type", "quantity",
    "resolved_part_id", "free_of_charge", "total_cost_cents", "status",
    "seq_no",
)
DEVICE_FIELDS = COMMON + (
    "sale_id", "app_account_id", "pairing_token", "firmware_version", "status",
)


def _pub(entity, fields):
    return {k: entity.get(k) for k in fields}


def season_out(e):
    return _pub(e, SEASON_FIELDS)


def model_out(e):
    return _pub(e, MODEL_FIELDS)


def channel_out(e):
    return _pub(e, CHANNEL_FIELDS)


def lot_out(e):
    derive.refresh_lot_actual(e)  # clock-dependent: lazy recompute on read
    return _pub(e, LOT_FIELDS)


def allocation_out(e):
    return _pub(e, ALLOCATION_FIELDS)


def assembler_out(e):
    derive.refresh_assembler_provisional(e)  # clock-dependent rolling window
    return _pub(e, ASSEMBLER_FIELDS)


def job_out(e):
    return _pub(e, JOB_FIELDS)


def sale_out(e):
    return _pub(e, SALE_FIELDS)


def claim_out(e):
    return _pub(e, CLAIM_FIELDS)


def part_out(e):
    return _pub(e, PART_FIELDS)


def parts_order_out(e):
    return _pub(e, PARTS_ORDER_FIELDS)


def device_out(e):
    return _pub(e, DEVICE_FIELDS)
