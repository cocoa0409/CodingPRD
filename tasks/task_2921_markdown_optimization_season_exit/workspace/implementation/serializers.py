"""Row -> JSON projections. Field sets follow SCAFFOLD entities exactly."""

BASE_VERSIONED = ("id", "created_at", "updated_at", "version")
BASE_PLAIN = ("id", "created_at")

SEASON_FIELDS = BASE_VERSIONED + (
    "code", "category", "season_start_date", "season_end_date",
    "exit_target_date", "exit_units_target", "sell_through_target_pct",
    "clearance_space_units", "reserved_clearance_units",
    "committed_clearance_units", "projected_exit_units", "status",
)

PRICE_ZONE_FIELDS = BASE_VERSIONED + (
    "zone_code", "zone_type", "parent_zone_id", "region_code",
    "signage_lead_days",
)

STORE_FIELDS = BASE_VERSIONED + (
    "store_number", "price_zone_id", "region_code", "clearance_bay_units",
    "committed_clearance_units", "available_clearance_units", "status",
)

ITEM_FIELDS = BASE_VERSIONED + (
    "sku", "season_id", "category", "cluster_code", "vendor_code",
    "first_receipt_date", "protected_until_date", "original_retail_cents",
    "current_retail_cents", "unit_cost_cents", "units_received_total",
    "units_sold_total", "units_committed_disposition", "units_disposed_total",
    "on_hand_units", "sample_weeks", "sell_through_pct", "weeks_of_supply",
    "lifecycle_stage", "markdown_state", "permanent_markdown_reserve_cents",
    "promo_discount_cents",
)

SALES_WEEK_FIELDS = BASE_PLAIN + (
    "item_id", "week_ending_date", "units_sold", "ticket_price_cents",
    "price_relative_pct",
)

ESTIMATE_FIELDS = BASE_VERSIONED + (
    "item_id", "method", "resolved_method", "elasticity_coefficient",
    "sample_weeks_used", "peer_items_used", "confidence", "estimated_at",
    "certified_at", "status",
)

PLAN_FIELDS = BASE_VERSIONED + (
    "season_id", "item_id", "elasticity_estimate_id", "plan_type",
    "exit_date_target", "created_by_user_id", "approved_by_user_id",
    "revision_round", "recommended_depth_pct", "ladder_step_count",
    "gross_markdown_cents", "vendor_funded_cents", "net_markdown_cents",
    "projected_exit_units", "superseded_by_plan_id", "status",
)

STEP_FIELDS = BASE_VERSIONED + (
    "markdown_plan_id", "step_index", "effective_date", "depth_pct",
    "price_cents", "window_end_date_exclusive", "status",
)

EXECUTION_FIELDS = BASE_VERSIONED + (
    "markdown_plan_id", "markdown_step_id", "price_zone_id", "store_id",
    "execution_scope", "effective_date", "units_in_scope", "signage_due_date",
    "signage_status", "posted_at", "posted_by_user_id", "verified_by_user_id",
    "per_unit_markdown_cents", "line_markdown_cents", "price_cents_applied",
    "applied_at", "status",
)

RESERVATION_FIELDS = BASE_VERSIONED + (
    "season_id", "store_id", "markdown_plan_id", "reserved_units",
    "allocation_rank", "released_at", "status",
)

AGREEMENT_FIELDS = BASE_VERSIONED + (
    "season_id", "vendor_code", "item_category_scope", "current_share_pct",
    "current_cap_cents", "agreed_share_pct", "funding_cap_cents",
    "remaining_cap_cents", "recognized_total_cents", "round_index",
    "last_offer_by_role", "last_offer_by_user_id", "status",
)

CLAIM_FIELDS = BASE_VERSIONED + (
    "allowance_agreement_id", "markdown_plan_id", "claimed_cents",
    "recognized_cents", "recognized_by_user_id", "rejection_reason", "status",
)

DISPOSITION_FIELDS = BASE_VERSIONED + (
    "season_id", "item_id", "channel", "units", "unit_recovery_cents",
    "fmv_cents", "projected_recovery_cents", "settled_units",
    "settled_recovery_cents", "created_by_user_id", "approved_by_user_id",
    "status",
)

EXIT_REVIEW_FIELDS = BASE_PLAIN + (
    "season_id", "review_type", "revenue_cents", "cogs_cents",
    "markdown_reserve_cents", "promo_discount_cents", "vendor_funding_cents",
    "disposition_recovery_cents", "gross_margin_cents", "sell_through_pct",
    "units_received_total", "units_sold_total", "units_disposed_total",
    "exit_units_variance", "sell_through_variance_pct", "generated_at",
    "generated_by_user_id",
)


def _project(row, fields):
    return {name: row.get(name) for name in fields}


def season_json(row):
    return _project(row, SEASON_FIELDS)


def price_zone_json(row):
    return _project(row, PRICE_ZONE_FIELDS)


def store_json(row):
    return _project(row, STORE_FIELDS)


def item_json(row):
    return _project(row, ITEM_FIELDS)


def sales_week_json(row):
    return _project(row, SALES_WEEK_FIELDS)


def estimate_json(row):
    return _project(row, ESTIMATE_FIELDS)


def plan_json(row):
    return _project(row, PLAN_FIELDS)


def step_json(row):
    return _project(row, STEP_FIELDS)


def execution_json(row):
    return _project(row, EXECUTION_FIELDS)


def reservation_json(row):
    return _project(row, RESERVATION_FIELDS)


def agreement_json(row):
    return _project(row, AGREEMENT_FIELDS)


def claim_json(row):
    return _project(row, CLAIM_FIELDS)


def disposition_json(row):
    return _project(row, DISPOSITION_FIELDS)


def exit_review_json(row):
    return _project(row, EXIT_REVIEW_FIELDS)
