"""Entity assertions and the three conserved-ledger invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_timestamp, timestamps_equal

SEGMENT_TIERS = ["BEST", "CORE", "OCCASIONAL", "LAPSED", "DORMANT"]
CONTACT_STRATEGIES = ["PREMIUM_FULL", "STANDARD", "REACTIVATION", "SUPPRESS_ONLY"]
RENTAL_STATUSES = [
    "REQUESTED", "MODELED", "ORDERED", "DELIVERED", "NETTED", "CANCELLED",
]
MERGE_PURGE_STATUSES = ["PENDING", "COMPLETED", "FAILED", "SUPERSEDED", "STALE"]
PLAN_STATUSES = ["DRAFT", "COSTED", "UNDER_REVIEW", "APPROVED", "CANCELLED"]
PRODUCTION_STATUSES = ["PLANNED", "PRESORTED", "MAILED", "DELIVERED", "CANCELLED"]
MEASUREMENT_STATUSES = ["PENDING", "MATCHBACK_OPEN", "MATCHBACK_CLOSED"]
COST_BASES = ["ESTIMATED_POSTAGE", "PRESORTED_ACTUAL"]
LINE_STATUSES = ["PROPOSED", "ALLOCATED", "SUPPRESSED", "VOIDED"]
PLACEMENT_POSITIONS = ["FRONT_COVER", "HOT_SPOT", "INSIDE", "BACK_COVER"]
PRESORT_TIERS = ["FIVE_DIGIT", "THREE_DIGIT", "AADC", "MIXED_AADC"]
CONTACT_CHANNELS = ["MAIL", "EMAIL", "DIGITAL"]
CONTACT_SOURCES = ["DROP_MAIL_CASCADE", "MANUAL_LOG"]
TEST_CELL_STATUSES = ["PLANNED", "MEASURED"]
SIGNIFICANCES = [
    "UNMEASURED", "INSUFFICIENT_SAMPLE", "INSUFFICIENT_CONTROL",
    "SIGNIFICANT", "NOT_SIGNIFICANT",
]
MATCHBACK_STATUSES = ["OPEN", "FINALIZED", "SUPERSEDED"]


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------
def assert_identity(data: dict) -> None:
    """Every persisted resource carries a server-minted UUID id and a
    created_at instant."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )


def assert_versioned(data: dict) -> None:
    """A living resource additionally carries updated_at and an integer
    version starting at 1."""
    assert_identity(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_immutable_audit_row(data: dict) -> None:
    """An immutable audit row carries only id and created_at: no updated_at
    field and no version field."""
    assert_identity(data)
    assert "updated_at" not in data, (
        f"immutable audit row must not carry updated_at: {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"immutable audit row must not carry version: {data.get('version')!r}"
    )


def assert_instant_equals(actual, expected, label="instant") -> None:
    """Compare two ISO 8601 instants irrespective of fractional-digit width."""
    assert timestamps_equal(actual, expected), (
        f"{label}: expected {canonical_timestamp(expected)}, "
        f"got {canonical_timestamp(actual)}"
    )


def assert_integer_fields(data: dict, *names) -> None:
    for name in names:
        assert isinstance(data.get(name), int) and not isinstance(
            data.get(name), bool
        ), f"{name} must be a JSON integer, got {data.get(name)!r}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_catalog_season(data: dict) -> None:
    assert_versioned(data)
    assert isinstance(data["season_code"], str) and 1 <= len(data["season_code"]) <= 32
    assert_integer_fields(
        data,
        "fiscal_year",
        "print_cost_per_page_per_thousand_cents",
        "paper_cost_per_lb_cents",
        "paper_oz_per_page_milli",
        "usable_sq_in_per_page",
        "default_postage_estimate_cents_per_piece",
        "cogs_rate_bps",
        "prospect_base_response_bps",
        "prospect_avg_order_value_cents",
        "min_inhome_gap_days",
        "fatigue_window_days",
        "fatigue_suppression_threshold",
    )
    assert 2020 <= data["fiscal_year"] <= 2100
    assert 0 <= data["cogs_rate_bps"] <= 10000
    assert data["paper_oz_per_page_milli"] > 0
    assert data["usable_sq_in_per_page"] > 0
    assert data["fatigue_window_days"] > 0
    assert data["fatigue_suppression_threshold"] > 0


def assert_housefile_segment(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert data.get("parent_segment_id") is None or is_valid_uuid(
        data["parent_segment_id"]
    )
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert_integer_fields(
        data,
        "recency_days",
        "orders_12mo",
        "ltv_cents",
        "housefile_count",
        "avg_order_value_cents",
        "historical_response_rate_bps",
        "rfm_score",
        "rollup_housefile_count",
        "fatigue_score",
    )
    assert 0 <= data["historical_response_rate_bps"] <= 10000
    assert 0 <= data["rfm_score"] <= 1000
    assert data["segment_tier"] in SEGMENT_TIERS
    assert data["contact_strategy"] in CONTACT_STRATEGIES
    assert isinstance(data["is_leaf"], bool)
    assert data["rollup_housefile_count"] >= data["housefile_count"]
    if data.get("suppressed_at") is not None:
        assert is_iso8601_timestamp(data["suppressed_at"])


def assert_prospect_list_rental(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["list_source_name"], str) and data["list_source_name"]
    assert_integer_fields(
        data,
        "requested_gross_names",
        "cost_per_thousand_cents",
        "housefile_overlap_bps",
        "inter_list_overlap_bps",
        "coop_model_score",
        "expected_response_rate_bps",
        "gross_names",
        "net_names_delivered",
        "unit_cost_cents_per_name",
    )
    assert data["requested_gross_names"] > 0
    assert 0 <= data["housefile_overlap_bps"] <= 10000
    assert 0 <= data["inter_list_overlap_bps"] <= 10000
    assert 0 <= data["coop_model_score"] <= 1000
    assert data["status"] in RENTAL_STATUSES


def assert_merge_purge_run(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("circulation_plan_id", ""))
    assert isinstance(data["input_rental_ids"], list)
    assert isinstance(data["processing_order"], list)
    assert_integer_fields(
        data,
        "observed_plan_version",
        "housefile_leaf_segment_count",
        "gross_input_names",
        "suppressed_names",
        "duplicates_removed",
        "net_mailable_names",
    )
    assert data["status"] in MERGE_PURGE_STATUSES
    assert_merge_purge_names_conserved(data)


def assert_circulation_plan(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert_integer_fields(
        data,
        "budget_cents",
        "revision_round",
        "committed_cost_cents",
        "uncommitted_budget_cents",
        "planned_cost_cents",
        "planned_demand_cents",
        "planned_contribution_cents",
    )
    assert data["budget_cents"] > 0
    assert data["status"] in PLAN_STATUSES
    for field in ("costed_by_user_id", "submitted_by_user_id", "approved_by_user_id"):
        assert data.get(field) is None or isinstance(data[field], str)
    assert_plan_budget_conserved(data)


def assert_drop(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("circulation_plan_id", ""))
    assert 1 <= data["drop_number"] <= 99
    assert is_iso8601_timestamp(data["in_home_date"])
    assert_integer_fields(
        data,
        "drop_number",
        "page_count",
        "square_inch_capacity",
        "allocated_square_inches",
        "unallocated_square_inches",
        "requested_quantity_total",
        "planned_quantity",
        "weight_oz_milli",
        "print_rebate_bps",
        "printing_cents_per_book",
        "paper_cents_per_book",
        "postage_cents_per_book",
        "cost_per_book_cents",
        "provisional_cost_per_book_cents",
        "postage_total_cents",
        "automation_share_bps",
    )
    assert 8 <= data["page_count"] <= 240 and data["page_count"] % 2 == 0
    assert data["cost_basis"] in COST_BASES
    assert isinstance(data["automation_qualified"], bool)
    assert data["production_status"] in PRODUCTION_STATUSES
    assert data["measurement_status"] in MEASUREMENT_STATUSES
    if data.get("mailed_at") is not None:
        assert is_iso8601_timestamp(data["mailed_at"])
    assert_drop_space_conserved(data)
    assert data["cost_per_book_cents"] == (
        data["printing_cents_per_book"]
        + data["paper_cents_per_book"]
        + data["postage_cents_per_book"]
    ), "cost_per_book_cents must be the sum of its three components"


def assert_circulation_line(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("drop_id", ""))
    assert data["audience_type"] in ["HOUSEFILE", "RENTAL"]
    assert_integer_fields(
        data,
        "requested_quantity",
        "holdout_pct_bps",
        "allocation_rank",
        "allocated_quantity",
        "holdout_quantity",
        "mailable_quantity",
        "unit_cost_cents",
        "committed_cost_cents",
        "effective_response_bps",
        "gross_forecast_demand_cents",
        "forecast_demand_cents",
        "gross_margin_cents",
        "circulation_cost_cents",
        "contribution_cents",
    )
    assert data["requested_quantity"] > 0
    assert 0 <= data["holdout_pct_bps"] <= 5000
    assert isinstance(data["is_holdout"], bool)
    assert data["status"] in LINE_STATUSES
    if data["audience_type"] == "HOUSEFILE":
        assert is_valid_uuid(data.get("housefile_segment_id", ""))
        assert data.get("prospect_list_rental_id") is None
    else:
        assert is_valid_uuid(data.get("prospect_list_rental_id", ""))
        assert data.get("housefile_segment_id") is None
    assert data["mailable_quantity"] == (
        data["allocated_quantity"] - data["holdout_quantity"]
    ), "mailable_quantity must be allocated_quantity less holdout_quantity"


def assert_page_placement(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("drop_id", ""))
    assert isinstance(data["product_sku"], str) and data["product_sku"]
    assert_integer_fields(
        data,
        "unit_price_cents",
        "unit_cogs_cents",
        "demand_per_sq_inch_cents",
        "page_number",
        "sq_in_offset",
        "square_inches",
        "position_multiplier_bps",
        "forecast_space_demand_cents",
        "space_productivity_cents_per_sq_in",
    )
    assert data["square_inches"] > 0
    assert data["sq_in_offset"] >= 0
    assert data["page_number"] >= 1
    assert data["placement_position"] in PLACEMENT_POSITIONS


def assert_postal_presort_batch(data: dict) -> None:
    assert_immutable_audit_row(data)
    assert is_valid_uuid(data.get("drop_id", ""))
    assert data["declared_tier"] in PRESORT_TIERS
    assert data["effective_tier"] in PRESORT_TIERS
    assert_integer_fields(
        data,
        "piece_count",
        "rate_cents_per_piece",
        "weight_surcharge_cents_per_piece",
        "batch_postage_cents",
    )
    assert data["piece_count"] > 0
    assert isinstance(data["is_automation_qualified"], bool)
    assert data["batch_postage_cents"] == data["piece_count"] * (
        data["rate_cents_per_piece"] + data["weight_surcharge_cents_per_piece"]
    ), "batch_postage_cents folds the surcharge into the per-piece rate"


def assert_contact_event(data: dict) -> None:
    assert_immutable_audit_row(data)
    assert is_valid_uuid(data.get("housefile_segment_id", ""))
    assert data.get("drop_id") is None or is_valid_uuid(data["drop_id"])
    assert data["channel"] in CONTACT_CHANNELS
    assert is_iso8601_timestamp(data["contact_date"])
    assert data["source"] in CONTACT_SOURCES
    assert_integer_fields(data, "channel_weight", "decay_factor_bps", "weighted_points")


def assert_suppression_rule(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["channel_scope"] in ["MAIL", "EMAIL", "DIGITAL", "ALL"]
    assert_integer_fields(data, "window_days", "max_contacts_per_window", "priority")
    assert 1 <= data["window_days"] <= 365
    assert data["max_contacts_per_window"] >= 0
    assert data["priority"] >= 1
    assert isinstance(data["is_enabled"], bool)


def assert_test_cell(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("circulation_line_id", ""))
    assert isinstance(data["cell_code"], str) and data["cell_code"]
    assert data["test_type"] in ["SEGMENT", "FORMAT", "OFFER"]
    assert data["cell_role"] in ["TEST", "CONTROL", "HOLDOUT"]
    assert_integer_fields(
        data, "quantity", "responders", "demand_cents", "response_rate_bps", "lift_bps"
    )
    assert data["quantity"] > 0
    assert data["responders"] <= data["quantity"]
    assert data["significance"] in SIGNIFICANCES
    assert data["status"] in TEST_CELL_STATUSES


def assert_matchback_run(data: dict) -> None:
    assert_versioned(data)
    assert is_valid_uuid(data.get("drop_id", ""))
    assert data["attribution_variant"] in [
        "LAST_TOUCH_MAIL", "FRACTIONAL_MULTI_TOUCH",
    ]
    assert_integer_fields(
        data,
        "attribution_window_days",
        "observed_drop_version",
        "matched_order_count",
        "attributed_order_count",
        "unmatched_order_count",
        "attributed_demand_cents",
    )
    assert 1 <= data["attribution_window_days"] <= 180
    assert data["status"] in MATCHBACK_STATUSES
    if data.get("finalized_at") is not None:
        assert is_iso8601_timestamp(data["finalized_at"])
    assert data["unmatched_order_count"] == (
        data["matched_order_count"] - data["attributed_order_count"]
    ), "unmatched_order_count is matched_order_count less attributed_order_count"


# --------------------------------------------------------------------------
# The three conserved ledgers
# --------------------------------------------------------------------------
def assert_plan_budget_conserved(plan: dict) -> None:
    """budget_cents equals committed_cost_cents plus uncommitted_budget_cents
    with no drift whatsoever."""
    assert plan["budget_cents"] == (
        plan["committed_cost_cents"] + plan["uncommitted_budget_cents"]
    ), (
        f"budget identity broken: {plan['budget_cents']} != "
        f"{plan['committed_cost_cents']} + {plan['uncommitted_budget_cents']}"
    )


def assert_merge_purge_names_conserved(run: dict) -> None:
    """gross_input_names equals net_mailable_names plus suppressed_names plus
    duplicates_removed."""
    assert run["gross_input_names"] == (
        run["net_mailable_names"] + run["suppressed_names"] + run["duplicates_removed"]
    ), (
        f"name conservation broken: {run['gross_input_names']} != "
        f"{run['net_mailable_names']} + {run['suppressed_names']} + "
        f"{run['duplicates_removed']}"
    )


def assert_drop_space_conserved(drop: dict) -> None:
    """square_inch_capacity equals allocated_square_inches plus
    unallocated_square_inches."""
    assert drop["square_inch_capacity"] == (
        drop["allocated_square_inches"] + drop["unallocated_square_inches"]
    ), (
        f"space identity broken: {drop['square_inch_capacity']} != "
        f"{drop['allocated_square_inches']} + {drop['unallocated_square_inches']}"
    )


def assert_line_zeroed(line: dict) -> None:
    """A line that has left ALLOCATED carries no allocated, committed, margin
    or cost figures."""
    for field in (
        "allocated_quantity",
        "holdout_quantity",
        "mailable_quantity",
        "forecast_demand_cents",
        "gross_margin_cents",
        "circulation_cost_cents",
        "contribution_cents",
        "committed_cost_cents",
    ):
        assert line[field] == 0, f"{field} must be 0 on a retired line, got {line[field]}"


def assert_ordered_by(rows, key, descending=False) -> None:
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {key} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )
