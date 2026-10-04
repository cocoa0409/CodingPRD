"""Entity assertions and domain invariant checkers.

Per-entity assert_* functions validate the stored-field surface of each
entity. QualificationRun is the sole append-only entity: its assertion
REQUIRES the absence of updated_at and version.

Status-aware success wrappers (validate_created / validate_ok) take the
expected HTTP status explicitly at the named call — creates return 201,
actions and reads return 200; there is no silent 200 default wrapping
create calls.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    validate_success,
)


# ─── Status-explicit success wrappers ────────────────────────────────────────

def validate_created(response) -> dict:
    """Creation endpoints respond HTTP 201 with the created resource."""
    return validate_success(response, 201)


def validate_ok(response) -> dict:
    """Action and read endpoints respond HTTP 200."""
    return validate_success(response, 200)


# ─── Shared scalar checks ────────────────────────────────────────────────────

def _assert_common_fields(data: dict, entity_label: str):
    """id + created_at + updated_at + version (all entities except QualificationRun)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


def _assert_nullable_timestamp(data: dict, field: str, entity_label: str):
    value = data.get(field, "__ABSENT__")
    assert value != "__ABSENT__", f"{entity_label}.{field} key must be present (null allowed)"
    if value is not None:
        assert is_iso8601_timestamp(value), (
            f"{entity_label}.{field} must be ISO 8601 UTC when not null"
        )


def _assert_score_2dp(value, field: str, entity_label: str):
    """Scores/percentages: numeric, 0..100, at most 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{entity_label}.{field} must be numeric"
    )
    assert 0 <= value <= 100, f"{entity_label}.{field} must lie in 0..100, got {value}"
    rounded = round(float(value), 2)
    assert abs(rounded - float(value)) < 1e-9, (
        f"{entity_label}.{field} must carry at most 2 decimal places, got {value}"
    )


# ─── Per-entity assertions ───────────────────────────────────────────────────

def assert_brand(data: dict):
    _assert_common_fields(data, "Brand")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["category_name"], str)
    assert isinstance(data["core_flag"], bool)
    assert isinstance(data["private_label_share_pct"], int)
    assert 0 <= data["private_label_share_pct"] <= 100
    assert isinstance(data["annual_net_revenue_cents"], int)
    assert data["annual_net_revenue_cents"] >= 0
    assert data["brand_status"] in (
        "ACTIVE", "UNDER_REVIEW", "DIVESTING", "DIVESTED", "EXITED",
    )


def assert_item(data: dict):
    _assert_common_fields(data, "Item")
    assert isinstance(data["brand_id"], str) and data["brand_id"]
    assert isinstance(data["primary_plant_id"], str) and data["primary_plant_id"]
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["annual_units"], int) and data["annual_units"] >= 0
    assert isinstance(data["unit_net_revenue_cents"], int)
    assert data["unit_net_revenue_cents"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["units_on_hand"], int) and data["units_on_hand"] >= 0
    assert isinstance(data["salvageable"], bool)
    assert data["item_status"] in (
        "LISTED", "CUT_PROPOSED", "SELL_THROUGH", "DISCONTINUED",
    )
    _assert_nullable_timestamp(data, "sell_through_deadline", "Item")
    assert isinstance(data["units_sold_cumulative"], int)
    assert data["units_sold_cumulative"] >= 0
    assert isinstance(data["units_written_off_cumulative"], int)
    assert data["units_written_off_cumulative"] >= 0
    assert isinstance(data["obsolescence_charge_cents"], int)
    assert data["obsolescence_charge_cents"] >= 0


def assert_plant(data: dict):
    _assert_common_fields(data, "Plant")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["quarterly_capacity_units"], int)
    assert data["quarterly_capacity_units"] > 0
    assert data["plant_status"] in ("OPERATING", "CLOSING", "CLOSED")
    _assert_nullable_timestamp(data, "closure_date", "Plant")
    assert isinstance(data["committed_units_per_quarter"], int)
    assert data["committed_units_per_quarter"] >= 0
    assert isinstance(data["utilization_pct"], (int, float))
    assert data["utilization_pct"] >= 0


def assert_retailer(data: dict):
    _assert_common_fields(data, "Retailer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["risk_rating"] in ("LOW", "MEDIUM", "HIGH")


def assert_rationalization_case(data: dict):
    _assert_common_fields(data, "RationalizationCase")
    assert isinstance(data["item_id"], str) and data["item_id"]
    assert isinstance(data["proposer_user_id"], str) and data["proposer_user_id"]
    _assert_score_2dp(data["volume_score"], "volume_score", "RationalizationCase")
    _assert_score_2dp(data["margin_score"], "margin_score", "RationalizationCase")
    _assert_score_2dp(
        data["shelf_resilience_score"], "shelf_resilience_score", "RationalizationCase"
    )
    _assert_score_2dp(
        data["backlash_resilience_score"], "backlash_resilience_score",
        "RationalizationCase",
    )
    _assert_score_2dp(data["composite_score"], "composite_score", "RationalizationCase")
    assert data["recommendation"] in ("CUT", "KEEP")
    assert data["case_status"] in (
        "SCORED", "EXECUTING", "REJECTED", "EXECUTED", "VOIDED",
    )
    # decider_user_id is null until decide (or the literal 'system' on cascade void)
    assert "decider_user_id" in data, "decider_user_id key must be present (null allowed)"
    if data["decider_user_id"] is not None:
        assert isinstance(data["decider_user_id"], str)


def assert_divestiture(data: dict):
    _assert_common_fields(data, "Divestiture")
    assert isinstance(data["brand_id"], str) and data["brand_id"]
    assert isinstance(data["acquirer_name"], str) and data["acquirer_name"]
    assert isinstance(data["headline_price_cents"], int)
    assert data["headline_price_cents"] >= 0
    assert is_iso8601_timestamp(data["expected_close_date"])
    assert data["divestiture_status"] in (
        "PROPOSED", "SPA_SIGNED", "CLOSED", "SEPARATED",
    )


def assert_tsa(data: dict):
    _assert_common_fields(data, "TransitionServiceAgreement")
    assert isinstance(data["divestiture_id"], str) and data["divestiture_id"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["tsa_status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    _assert_nullable_timestamp(data, "terminated_at", "TransitionServiceAgreement")
    assert isinstance(data["early_termination_penalty_cents"], int)
    assert data["early_termination_penalty_cents"] >= 0


def assert_product_transfer(data: dict):
    _assert_common_fields(data, "ProductTransfer")
    assert isinstance(data["item_id"], str) and data["item_id"]
    assert isinstance(data["source_plant_id"], str) and data["source_plant_id"]
    assert isinstance(data["target_plant_id"], str) and data["target_plant_id"]
    assert data["transfer_status"] in ("PLANNED", "QUALIFYING", "EXECUTED")
    assert isinstance(data["consecutive_pass_count"], int)
    assert data["consecutive_pass_count"] >= 0


def assert_qualification_run(data: dict):
    """Append-only event record: id + created_at ONLY — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "QualificationRun.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "QualificationRun.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, (
        "QualificationRun is immutable: updated_at must be absent"
    )
    assert "version" not in data, (
        "QualificationRun is immutable: version must be absent"
    )
    assert isinstance(data["transfer_id"], str) and data["transfer_id"]
    assert is_iso8601_timestamp(data["run_date"])
    assert isinstance(data["units_produced"], int) and data["units_produced"] >= 1
    assert isinstance(data["units_rejected"], int) and data["units_rejected"] >= 0
    assert data["units_rejected"] <= data["units_produced"]
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["certifier_plant_id"], str) and data["certifier_plant_id"]


def assert_combined_negotiation(data: dict):
    _assert_common_fields(data, "CombinedNegotiation")
    assert isinstance(data["retailer_id"], str) and data["retailer_id"]
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert isinstance(data["brand_terms"], list)
    for term in data["brand_terms"]:
        assert isinstance(term["brand_id"], str) and term["brand_id"]
        assert isinstance(term["baseline_facings"], int) and term["baseline_facings"] >= 0
        assert isinstance(term["proposed_facings"], int) and term["proposed_facings"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["total_baseline_facings"], int)
    assert data["total_baseline_facings"] >= 0
    assert isinstance(data["total_proposed_facings"], int)
    assert data["total_proposed_facings"] >= 0
    _assert_score_2dp(
        data["shelf_reduction_pct"], "shelf_reduction_pct", "CombinedNegotiation"
    )
    assert data["negotiation_status"] in (
        "TERMS_PROPOSED", "ACCEPTED", "REJECTED", "EXPIRED",
    )
    assert is_iso8601_timestamp(data["expires_at"])


def assert_capital_cycle(data: dict):
    _assert_common_fields(data, "CapitalCycle")
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert isinstance(data["total_capital_cents"], int)
    assert data["total_capital_cents"] > 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["remaining_cents"], (int, float))
    assert data["cycle_status"] in ("ALLOCATING", "LOCKED")


def assert_innovation_project(data: dict):
    _assert_common_fields(data, "InnovationProject")
    assert isinstance(data["brand_id"], str) and data["brand_id"]
    assert isinstance(data["funding_cycle_id"], str) and data["funding_cycle_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["requested_capital_cents"], int)
    assert data["requested_capital_cents"] > 0
    assert isinstance(data["expected_revenue_cents_year3"], int)
    assert data["expected_revenue_cents_year3"] >= 0
    assert isinstance(data["strategic_fit_score"], int)
    assert 0 <= data["strategic_fit_score"] <= 100
    _assert_score_2dp(data["priority_score"], "priority_score", "InnovationProject")
    assert data["project_status"] in ("PROPOSED", "FUNDED", "DEFERRED")


# ─── Domain invariants ───────────────────────────────────────────────────────

def assert_item_unit_balance(item: dict, created_units_on_hand: int):
    """Unit conservation: on-hand + sold + written-off == creation balance.

    Holds across every sell-down, finalize, and divestiture-cascade write-off.
    """
    total = (
        item["units_on_hand"]
        + item["units_sold_cumulative"]
        + item["units_written_off_cumulative"]
    )
    assert total == created_units_on_hand, (
        f"Item unit balance broken: {item['units_on_hand']} on hand + "
        f"{item['units_sold_cumulative']} sold + "
        f"{item['units_written_off_cumulative']} written off = {total}, "
        f"expected {created_units_on_hand} (creation balance)"
    )


def assert_capital_conservation(cycle: dict):
    """allocated_cents + remaining_cents == total_capital_cents after selection."""
    total = cycle["allocated_cents"] + cycle["remaining_cents"]
    assert total == cycle["total_capital_cents"], (
        f"Capital conservation broken: {cycle['allocated_cents']} allocated + "
        f"{cycle['remaining_cents']} remaining = {total}, "
        f"expected {cycle['total_capital_cents']}"
    )
