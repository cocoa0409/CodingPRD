"""Domain assertions: entity shape checks, rounding helpers and invariants."""

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AGREEMENT_STATUSES,
    CATEGORIES,
    CLAIM_STATUSES,
    DISPOSITION_CHANNELS,
    DISPOSITION_STATUSES,
    EXECUTION_SCOPES,
    EXECUTION_STATUSES,
    LIFECYCLE_STAGES,
    MARKDOWN_STATES,
    PLAN_STATUSES,
    PLAN_TYPES,
    RESERVATION_STATUSES,
    REVIEW_TYPES,
    SEASON_STATUSES,
    SIGNAGE_STATUSES,
    STEP_STATUSES,
    STORE_STATUSES,
    ZONE_TYPES,
)

DATE_ONLY_LENGTH = 10


# ==========================================================================
# Generic shape helpers
# ==========================================================================
def assert_date_only(value: Any, field: str = "date") -> None:
    """A selling-calendar date is a date-only YYYY-MM-DD value (PRD 2.4)."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == DATE_ONLY_LENGTH, f"{field} must be YYYY-MM-DD, got {value!r}"
    assert value[4] == "-" and value[7] == "-", f"{field} must be YYYY-MM-DD, got {value!r}"
    assert value[:4].isdigit() and value[5:7].isdigit() and value[8:].isdigit(), (
        f"{field} must be YYYY-MM-DD, got {value!r}"
    )


def assert_instant(value: Any, field: str = "timestamp") -> None:
    """An instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"


def assert_common_fields(entity: Dict[str, Any], name: str = "resource") -> None:
    """Most resources carry ``id``, ``created_at``, ``updated_at`` and ``version``."""
    assert is_valid_uuid(entity["id"]), f"{name}.id must be a UUID, got {entity['id']!r}"
    assert_instant(entity["created_at"], f"{name}.created_at")
    assert_instant(entity["updated_at"], f"{name}.updated_at")
    assert isinstance(entity["version"], int), f"{name}.version must be an integer"
    assert entity["version"] >= 1, f"{name}.version starts at 1"


def assert_append_only_fields(entity: Dict[str, Any], name: str = "resource") -> None:
    """Append-only resources carry only ``id`` and ``created_at`` (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"{name}.id must be a UUID, got {entity['id']!r}"
    assert_instant(entity["created_at"], f"{name}.created_at")
    assert "updated_at" not in entity, f"{name} must not carry updated_at"
    assert "version" not in entity, f"{name} must not carry version"


def assert_money_cents(value: Any, field: str) -> None:
    """Money is an integer number of cents; no monetary field is fractional."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_pct_two_decimals(value: Any, field: str) -> None:
    """Percentages carry exactly two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must carry at most two decimals, got {value!r}"
    )


def assert_four_decimals(value: Any, field: str) -> None:
    """Elasticity is the one quantity carried at four decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must carry at most four decimals, got {value!r}"
    )


def assert_pct(actual: Any, expected: float, field: str = "percentage") -> None:
    """Compare a two-decimal percentage against its expected value."""
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"{field} expected {expected}, got {actual}"
    )


# ==========================================================================
# Per-entity shape assertions
# ==========================================================================
def assert_season_shape(season: Dict[str, Any]) -> None:
    assert_common_fields(season, "season")
    assert isinstance(season["code"], str) and season["code"]
    assert season["category"] in CATEGORIES
    assert season["status"] in SEASON_STATUSES
    for field in ("season_start_date", "season_end_date", "exit_target_date"):
        assert_date_only(season[field], f"season.{field}")
    for field in (
        "exit_units_target",
        "clearance_space_units",
        "reserved_clearance_units",
        "committed_clearance_units",
        "projected_exit_units",
    ):
        assert isinstance(season[field], int), f"season.{field} must be an integer"
    assert_pct_two_decimals(
        season["sell_through_target_pct"], "season.sell_through_target_pct"
    )


def assert_price_zone_shape(zone: Dict[str, Any]) -> None:
    assert_common_fields(zone, "price_zone")
    assert isinstance(zone["zone_code"], str) and zone["zone_code"]
    assert zone["zone_type"] in ZONE_TYPES
    assert isinstance(zone["signage_lead_days"], int)
    assert 1 <= zone["signage_lead_days"] <= 30


def assert_store_shape(store: Dict[str, Any]) -> None:
    assert_common_fields(store, "store")
    assert isinstance(store["store_number"], str) and store["store_number"]
    assert is_valid_uuid(store["price_zone_id"])
    assert store["status"] in STORE_STATUSES
    for field in (
        "clearance_bay_units",
        "committed_clearance_units",
        "available_clearance_units",
    ):
        assert isinstance(store[field], int), f"store.{field} must be an integer"
    assert (
        store["available_clearance_units"]
        == store["clearance_bay_units"] - store["committed_clearance_units"]
    ), "available_clearance_units is the bay capacity less the committed sum"


def assert_item_shape(item: Dict[str, Any]) -> None:
    assert_common_fields(item, "item")
    assert isinstance(item["sku"], str) and item["sku"]
    assert is_valid_uuid(item["season_id"])
    assert item["category"] in CATEGORIES
    assert item["lifecycle_stage"] in LIFECYCLE_STAGES
    assert item["markdown_state"] in MARKDOWN_STATES
    assert_date_only(item["first_receipt_date"], "item.first_receipt_date")
    assert_date_only(item["protected_until_date"], "item.protected_until_date")
    for field in (
        "original_retail_cents",
        "current_retail_cents",
        "unit_cost_cents",
        "permanent_markdown_reserve_cents",
        "promo_discount_cents",
    ):
        assert_money_cents(item[field], f"item.{field}")
    for field in (
        "units_received_total",
        "on_hand_units",
        "units_sold_total",
        "units_committed_disposition",
        "units_disposed_total",
        "sample_weeks",
    ):
        assert isinstance(item[field], int), f"item.{field} must be an integer"
    assert_pct_two_decimals(item["sell_through_pct"], "item.sell_through_pct")
    assert_pct_two_decimals(item["weeks_of_supply"], "item.weeks_of_supply")
    assert (
        item["on_hand_units"]
        == item["units_received_total"] - item["units_sold_total"] - item["units_disposed_total"]
    ), "on_hand_units is units_received_total less units sold less units disposed"


def assert_sales_week_shape(week: Dict[str, Any]) -> None:
    assert_append_only_fields(week, "sales_week")
    assert is_valid_uuid(week["item_id"])
    assert_date_only(week["week_ending_date"], "sales_week.week_ending_date")
    assert isinstance(week["units_sold"], int)
    assert_money_cents(week["ticket_price_cents"], "sales_week.ticket_price_cents")
    assert_pct_two_decimals(week["price_relative_pct"], "sales_week.price_relative_pct")


def assert_elasticity_estimate_shape(estimate: Dict[str, Any]) -> None:
    assert_common_fields(estimate, "elasticity_estimate")
    assert is_valid_uuid(estimate["item_id"])
    assert estimate["resolved_method"] in ("OWN_HISTORY", "CLUSTER_POOLED"), (
        "resolved_method is always either OWN_HISTORY or CLUSTER_POOLED, never AUTO"
    )
    assert estimate["confidence"] in ("HIGH", "LOW")
    assert estimate["status"] in ("DRAFT", "CERTIFIED", "SUPERSEDED")
    assert_four_decimals(
        estimate["elasticity_coefficient"], "elasticity_estimate.elasticity_coefficient"
    )
    assert float(estimate["elasticity_coefficient"]) <= -0.2
    assert float(estimate["elasticity_coefficient"]) >= -4.0
    assert isinstance(estimate["sample_weeks_used"], int)
    assert isinstance(estimate["peer_items_used"], int)
    assert_instant(estimate["estimated_at"], "elasticity_estimate.estimated_at")


def assert_markdown_plan_shape(plan: Dict[str, Any]) -> None:
    assert_common_fields(plan, "markdown_plan")
    assert is_valid_uuid(plan["season_id"])
    assert is_valid_uuid(plan["item_id"])
    assert is_valid_uuid(plan["elasticity_estimate_id"])
    assert plan["plan_type"] in PLAN_TYPES
    assert plan["status"] in PLAN_STATUSES
    assert_date_only(plan["exit_date_target"], "markdown_plan.exit_date_target")
    assert_pct_two_decimals(
        plan["recommended_depth_pct"], "markdown_plan.recommended_depth_pct"
    )
    for field in ("gross_markdown_cents", "vendor_funded_cents", "net_markdown_cents"):
        assert_money_cents(plan[field], f"markdown_plan.{field}")
    for field in ("revision_round", "ladder_step_count", "projected_exit_units"):
        assert isinstance(plan[field], int), f"markdown_plan.{field} must be an integer"
    assert plan["net_markdown_cents"] == plan["gross_markdown_cents"] - plan["vendor_funded_cents"], (
        "net_markdown_cents is the gross less the vendor-funded amount"
    )


def assert_markdown_step_shape(step: Dict[str, Any]) -> None:
    assert_common_fields(step, "markdown_step")
    assert is_valid_uuid(step["markdown_plan_id"])
    assert isinstance(step["step_index"], int) and step["step_index"] >= 1
    assert_date_only(step["effective_date"], "markdown_step.effective_date")
    assert_pct_two_decimals(step["depth_pct"], "markdown_step.depth_pct")
    assert_money_cents(step["price_cents"], "markdown_step.price_cents")
    assert step["status"] in STEP_STATUSES


def assert_zone_execution_shape(execution: Dict[str, Any]) -> None:
    assert_common_fields(execution, "zone_execution")
    assert is_valid_uuid(execution["markdown_plan_id"])
    assert is_valid_uuid(execution["markdown_step_id"])
    assert is_valid_uuid(execution["price_zone_id"])
    assert execution["execution_scope"] in EXECUTION_SCOPES
    assert execution["status"] in EXECUTION_STATUSES
    assert execution["signage_status"] in SIGNAGE_STATUSES
    assert_date_only(execution["effective_date"], "zone_execution.effective_date")
    assert_date_only(execution["signage_due_date"], "zone_execution.signage_due_date")
    assert isinstance(execution["units_in_scope"], int) and execution["units_in_scope"] >= 1
    for field in (
        "per_unit_markdown_cents",
        "line_markdown_cents",
        "price_cents_applied",
    ):
        assert_money_cents(execution[field], f"zone_execution.{field}")
    if execution["execution_scope"] == "STORE":
        assert is_valid_uuid(execution["store_id"]), (
            "a STORE execution names the store whose shelf changes"
        )
    else:
        assert execution.get("store_id") is None, (
            "chain-scope and zone-scope executions carry no store_id at all"
        )


def assert_clearance_reservation_shape(reservation: Dict[str, Any]) -> None:
    assert_common_fields(reservation, "clearance_reservation")
    assert is_valid_uuid(reservation["season_id"])
    assert is_valid_uuid(reservation["store_id"])
    assert is_valid_uuid(reservation["markdown_plan_id"])
    assert isinstance(reservation["reserved_units"], int) and reservation["reserved_units"] >= 1
    assert isinstance(reservation["allocation_rank"], int) and reservation["allocation_rank"] >= 1
    assert reservation["status"] in RESERVATION_STATUSES


def assert_allowance_agreement_shape(agreement: Dict[str, Any]) -> None:
    assert_common_fields(agreement, "allowance_agreement")
    assert is_valid_uuid(agreement["season_id"])
    assert isinstance(agreement["vendor_code"], str) and agreement["vendor_code"]
    assert agreement["item_category_scope"] in CATEGORIES
    assert agreement["status"] in AGREEMENT_STATUSES
    assert_pct_two_decimals(
        agreement["current_share_pct"], "allowance_agreement.current_share_pct"
    )
    assert_money_cents(
        agreement["current_cap_cents"], "allowance_agreement.current_cap_cents"
    )
    assert_money_cents(
        agreement["recognized_total_cents"], "allowance_agreement.recognized_total_cents"
    )
    assert isinstance(agreement["round_index"], int) and agreement["round_index"] >= 1
    assert agreement["last_offer_by_role"] in ("PricingAnalyst", "VendorRep")


def assert_vendor_claim_shape(claim: Dict[str, Any]) -> None:
    assert_common_fields(claim, "vendor_claim")
    assert is_valid_uuid(claim["allowance_agreement_id"])
    assert is_valid_uuid(claim["markdown_plan_id"])
    assert_money_cents(claim["claimed_cents"], "vendor_claim.claimed_cents")
    assert_money_cents(claim["recognized_cents"], "vendor_claim.recognized_cents")
    assert claim["status"] in CLAIM_STATUSES


def assert_disposition_order_shape(order: Dict[str, Any]) -> None:
    assert_common_fields(order, "disposition_order")
    assert is_valid_uuid(order["season_id"])
    assert is_valid_uuid(order["item_id"])
    assert order["channel"] in DISPOSITION_CHANNELS
    assert order["status"] in DISPOSITION_STATUSES
    assert isinstance(order["units"], int) and order["units"] >= 1
    for field in (
        "projected_recovery_cents",
        "settled_units",
        "settled_recovery_cents",
    ):
        assert isinstance(order[field], int), f"disposition_order.{field} must be an integer"


def assert_exit_review_shape(review: Dict[str, Any]) -> None:
    assert_append_only_fields(review, "exit_review")
    assert is_valid_uuid(review["season_id"])
    assert review["review_type"] in REVIEW_TYPES
    assert_instant(review["generated_at"], "exit_review.generated_at")
    for field in (
        "revenue_cents",
        "cogs_cents",
        "markdown_reserve_cents",
        "promo_discount_cents",
        "vendor_funding_cents",
        "disposition_recovery_cents",
        "gross_margin_cents",
    ):
        assert_money_cents(review[field], f"exit_review.{field}")
    for field in ("units_received_total", "units_sold_total", "units_disposed_total"):
        assert isinstance(review[field], int)
    assert isinstance(review["exit_units_variance"], int)
    assert_pct_two_decimals(review["sell_through_pct"], "exit_review.sell_through_pct")
    assert_pct_two_decimals(
        review["sell_through_variance_pct"], "exit_review.sell_through_variance_pct"
    )
    assert review["gross_margin_cents"] == (
        review["revenue_cents"]
        - review["cogs_cents"]
        - review["markdown_reserve_cents"]
        - review["promo_discount_cents"]
        + review["vendor_funding_cents"]
        + review["disposition_recovery_cents"]
    ), (
        "gross_margin_cents is revenue less cost of goods, less markdown reserve, "
        "less promo discount, plus vendor funding, plus disposition recovery"
    )


# ==========================================================================
# Round-half-up arithmetic (PRD 2.8)
# ==========================================================================
def round_half_up(value: float, digits: int = 0) -> float:
    """Round half up: a tie at exactly half a unit rounds away from zero."""
    from decimal import ROUND_HALF_UP, Decimal

    quant = Decimal(1).scaleb(-digits)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(result) if digits else float(result)


def rung_price_cents(original_retail_cents: int, depth_pct: float) -> int:
    """The rung price: the discount is rounded to a whole cent first, then
    subtracted from the original ticket, and the price is never rounded again.
    """
    discount = int(round_half_up(original_retail_cents * depth_pct / 100.0, 0))
    return original_retail_cents - discount


def line_markdown_cents(per_unit_markdown_cents: int, units_in_scope: int) -> int:
    """The per-unit markdown is established first, then multiplied by the units
    in scope. Multiplying an unrounded per-unit amount by the unit count and
    rounding the product is explicitly not how a markdown line is computed.
    """
    return per_unit_markdown_cents * units_in_scope


# ==========================================================================
# The three conserved quantities (PRD 2.9)
# ==========================================================================
def item_markdown_exposure(item: Dict[str, Any]) -> int:
    """An item's markdown exposure is the sum of ``permanent_markdown_reserve_cents``
    and ``promo_discount_cents``.
    """
    return item["permanent_markdown_reserve_cents"] + item["promo_discount_cents"]


def assert_markdown_exposure_restored(
    item_before: Dict[str, Any], item_after: Dict[str, Any]
) -> None:
    """Applying an execution and then rolling the same execution back must leave
    the markdown exposure, and ``current_retail_cents``, at their pre-apply values.
    """
    assert item_markdown_exposure(item_after) == item_markdown_exposure(item_before), (
        "markdown exposure must return to its pre-apply value"
    )
    assert item_after["current_retail_cents"] == item_before["current_retail_cents"], (
        "current_retail_cents must return to its pre-apply value"
    )


def assert_agreement_cap_conserved(
    agreement: Dict[str, Any], recognized_claims: Iterable[Dict[str, Any]]
) -> None:
    """An agreement's ``funding_cap_cents`` always equals its ``remaining_cap_cents``
    plus the sum of ``recognized_cents`` across its ``RECOGNIZED`` claims.
    """
    recognized_sum = sum(
        claim["recognized_cents"]
        for claim in recognized_claims
        if claim["status"] == "RECOGNIZED"
    )
    assert agreement["funding_cap_cents"] == (
        agreement["remaining_cap_cents"] + recognized_sum
    ), "funding_cap_cents must equal remaining_cap_cents plus recognized claims"


def assert_store_clearance_conserved(
    store: Dict[str, Any], reservations: Iterable[Dict[str, Any]]
) -> None:
    """A store's ``clearance_bay_units`` always equals its ``available_clearance_units``
    plus the sum of ``reserved_units`` across its ``RESERVED`` and ``COMMITTED``
    reservations.
    """
    held = sum(
        reservation["reserved_units"]
        for reservation in reservations
        if reservation["status"] in ("RESERVED", "COMMITTED")
    )
    assert store["clearance_bay_units"] == store["available_clearance_units"] + held, (
        "clearance_bay_units must equal available plus reserved-or-committed units"
    )


def assert_season_counters(
    season: Dict[str, Any], reservations: Iterable[Dict[str, Any]]
) -> None:
    """The season's reserved and committed counters are the sums of ``reserved_units``
    across its reservations in each of those two states.
    """
    rows = list(reservations)
    reserved = sum(r["reserved_units"] for r in rows if r["status"] == "RESERVED")
    committed = sum(r["reserved_units"] for r in rows if r["status"] == "COMMITTED")
    assert season["reserved_clearance_units"] == reserved
    assert season["committed_clearance_units"] == committed


def assert_available_pool(item: Dict[str, Any], expected_available: int) -> None:
    """An item's uncommitted pool is its on-hand units less
    ``units_committed_disposition``.
    """
    actual = item["on_hand_units"] - item["units_committed_disposition"]
    assert actual == expected_available, (
        f"available pool expected {expected_available}, got {actual}"
    )


# ==========================================================================
# Small convenience helpers
# ==========================================================================
def find_by(rows: List[Dict[str, Any]], **criteria) -> Optional[Dict[str, Any]]:
    """First row matching every keyword criterion, or ``None``."""
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    return None


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    """``version`` increases by exactly ``delta`` across the pair of reads."""
    assert after["version"] == before["version"] + delta, (
        f"version expected {before['version'] + delta}, got {after['version']}"
    )
    assert after["updated_at"] >= before["updated_at"], (
        "updated_at is refreshed on the same occasions as version"
    )
