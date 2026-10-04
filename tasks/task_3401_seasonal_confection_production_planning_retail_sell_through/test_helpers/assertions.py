"""Entity assertions and PRD-pinned calculation helpers.

assert_<entity>(data) checks the structural contract: the PRD §2.4 common set
(id/created_at/updated_at/version), field presence and types, and enum
membership. The compute_* helpers re-derive expected values using the exact
formulas and rounding discipline of PRD §2.6 and §3 — round half-up to whole
cents for money, 4 decimal places round half-up for cannibalization ratios.
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CANNIBALIZATION_FLOOR,
    CONGESTED_PCT,
    HEAT_CLAIM_PCT_AUTO_APPROVE,
    HEAT_CLAIM_PCT_DECLINED,
    HEAT_CLAIM_PCT_GOODWILL,
    HEAT_CLAIM_PCT_TEMP_CONTROLLED,
    MAX_REOPEN,
    SEASONAL_LIFT,
    SECONDARY_RECOVERY_PCT,
    SHORTFALL_CREDIT_PCT,
    SUMMER_MONTHS,
)
from .types import (
    CommitmentStatus,
    Commodity,
    CommodityContractStatus,
    DispositionChannel,
    DispositionOrderStatus,
    HeatClaimReason,
    HeatClaimStatus,
    InventoryLotStatus,
    ProductKind,
    ProductionRunStatus,
    RetailerTier,
    SeasonalProgramStatus,
    SeasonCode,
    ShipmentStatus,
    WarehousePosture,
)


# ===========================================================================
# Rounding discipline (PRD §2.6)
# ===========================================================================

def round_half_up_int(value) -> int:
    """Round a numeric to a whole integer, half away from zero (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value) -> float:
    """Round a ratio to exactly 4 decimal places, half-up (PRD §2.6)."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ===========================================================================
# PRD §3 calculation re-derivations
# ===========================================================================

def compute_shortfall_credit(shortfall_units: int, retail_price_cents: int) -> int:
    """PRD §3.5: unmet units x retail price x 0.10, round half-up to cents."""
    return round_half_up_int(
        Decimal(shortfall_units) * Decimal(retail_price_cents) * Decimal(str(SHORTFALL_CREDIT_PCT))
    )


def compute_markdown_recovered_value(retail_price_cents: int, markdown_pct: float,
                                     units: int) -> int:
    """PRD §3.9 pinned order: round the per-unit price first, then multiply."""
    unit_price_after = (Decimal(retail_price_cents) * (Decimal("1") - Decimal(str(markdown_pct)))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(unit_price_after) * units


def compute_secondary_recovered_value(units: int, retail_price_cents: int) -> int:
    """PRD §3.9: units x retail price x 0.25, round half-up to whole cents."""
    return round_half_up_int(
        Decimal(units) * Decimal(retail_price_cents) * Decimal(str(SECONDARY_RECOVERY_PCT))
    )


def select_heat_claim_payout_pct(temp_controlled: bool,
                                 temp_control_declined_by_retailer: bool,
                                 requires_temp_control: bool,
                                 ship_on_iso: str) -> float:
    """PRD §3.8 pinned branch order: first matching branch wins."""
    if temp_controlled:
        return HEAT_CLAIM_PCT_TEMP_CONTROLLED
    if temp_control_declined_by_retailer:
        return HEAT_CLAIM_PCT_DECLINED
    ship_month = int(str(ship_on_iso)[5:7])
    if requires_temp_control and ship_month in SUMMER_MONTHS:
        return HEAT_CLAIM_PCT_AUTO_APPROVE
    return HEAT_CLAIM_PCT_GOODWILL


def compute_heat_claim_credit(claimed_units: int, retail_price_cents: int,
                              payout_pct: float) -> int:
    """PRD §3.8: claimed units x retail price x payout fraction, half-up."""
    return round_half_up_int(
        Decimal(claimed_units) * Decimal(retail_price_cents) * Decimal(str(payout_pct))
    )


def compute_auto_approve(requires_temp_control: bool, temp_controlled: bool,
                         temp_control_declined_by_retailer: bool,
                         ship_on_iso: str) -> bool:
    """PRD §3.8: true iff temp-required product, not temp-controlled, not
    declined by the retailer, and ship_on month in {6, 7, 8}."""
    ship_month = int(str(ship_on_iso)[5:7])
    return bool(
        requires_temp_control
        and not temp_controlled
        and not temp_control_declined_by_retailer
        and ship_month in SUMMER_MONTHS
    )


def compute_provisional_spend_cents(quantity_units: int, contract_price: int,
                                    hedged_quantity_units: int = 0,
                                    hedge_price: int = 0) -> int:
    """PRD §3.3 PROVISIONAL variant (reference price = contract price)."""
    payoff = max(0, contract_price - hedge_price)
    return quantity_units * contract_price - hedged_quantity_units * payoff


def compute_effective_spend_cents(quantity_units: int, spot_price: int,
                                  hedged_quantity_units: int = 0,
                                  hedge_price: int = 0) -> int:
    """PRD §3.3 FINAL variant (reference price = settlement spot price)."""
    payoff = max(0, spot_price - hedge_price)
    return quantity_units * spot_price - hedged_quantity_units * payoff


def compute_cannibalization_raw(everyday_units_sold: int,
                                everyday_baseline_weekly_units: int) -> float:
    """PRD §3.7 RAW variant, 4dp round half-up."""
    return round_half_up_4dp(
        Decimal(everyday_units_sold) / Decimal(everyday_baseline_weekly_units)
    )


def compute_cannibalization_adjusted(everyday_units_sold: int,
                                     everyday_baseline_weekly_units: int,
                                     season_code: str) -> float:
    """PRD §3.7 SEASONALLY_ADJUSTED variant, 4dp round half-up."""
    lift = Decimal(str(SEASONAL_LIFT[season_code]))
    return round_half_up_4dp(
        Decimal(everyday_units_sold) / (Decimal(everyday_baseline_weekly_units) * lift)
    )


def expected_warehouse_posture(in_use_units: int, capacity_units: int) -> str:
    """PRD §2.9: FULL at >= capacity; CONGESTED at >= floor(0.85 x capacity);
    boundaries are inclusive."""
    if in_use_units >= capacity_units:
        return WarehousePosture.FULL.value
    congested_floor = (Decimal(capacity_units) * Decimal(str(CONGESTED_PCT))).to_integral_value(
        rounding="ROUND_FLOOR"
    )
    if in_use_units >= int(congested_floor):
        return WarehousePosture.CONGESTED.value
    return WarehousePosture.OPEN.value


# ===========================================================================
# Entity assertions
# ===========================================================================

def _assert_common(data: dict, label: str) -> None:
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def _assert_iso(value, field: str, label: str) -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label}.{field} must be an ISO 8601 timestamp string"
    )


def assert_seasonal_program(data: dict) -> None:
    _assert_common(data, "SeasonalProgram")
    assert data["season_code"] in {s.value for s in SeasonCode}
    assert isinstance(data["season_year"], int) and data["season_year"] >= 2026
    for field in (
        "commitment_open_on", "commitment_close_on", "production_deadline_on",
        "ship_window_open_on", "ship_window_close_on", "on_shelf_on",
        "pull_on", "destroy_by_on",
    ):
        _assert_iso(data.get(field), field, "SeasonalProgram")
    assert isinstance(data["retail_price_cents"], int) and data["retail_price_cents"] > 0
    assert isinstance(data["forecast_units"], int) and data["forecast_units"] > 0
    for field in (
        "produced_units_total", "committed_units_total",
        "shipped_units_total", "disposed_units_total",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SeasonalProgram.{field} must be a non-negative integer"
        )
    assert isinstance(data["reopen_count"], int) and 0 <= data["reopen_count"] <= MAX_REOPEN
    assert data["status"] in {s.value for s in SeasonalProgramStatus}


def assert_product(data: dict) -> None:
    _assert_common(data, "Product")
    assert data["kind"] in {k.value for k in ProductKind}
    if data["kind"] == ProductKind.SEASONAL.value:
        assert isinstance(data.get("program_id"), str) and data["program_id"], (
            "SEASONAL product must name its program_id (PRD §3.1)"
        )
    else:
        assert data.get("program_id") is None, (
            "EVERYDAY product must carry a null program_id (PRD §3.1)"
        )
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["molded_shape"], str) and data["molded_shape"]
    assert isinstance(data["brand_protected"], bool)
    assert isinstance(data["requires_temp_control"], bool)
    assert isinstance(data["units_per_case"], int) and data["units_per_case"] > 0


def assert_production_run(data: dict) -> None:
    _assert_common(data, "ProductionRun")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert isinstance(data["produced_units"], int) and data["produced_units"] >= 0
    _assert_iso(data.get("scheduled_start_on"), "scheduled_start_on", "ProductionRun")
    _assert_iso(data.get("scheduled_end_on"), "scheduled_end_on", "ProductionRun")
    assert data["scheduled_end_on"] > data["scheduled_start_on"], (
        "ProductionRun end must be later than start (PRD §3.2)"
    )
    assert data.get("completed_warehouse_id") is None or isinstance(
        data["completed_warehouse_id"], str
    )
    assert data["status"] in {s.value for s in ProductionRunStatus}


def assert_retailer_account(data: dict) -> None:
    _assert_common(data, "RetailerAccount")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["tier"] in {t.value for t in RetailerTier}
    assert isinstance(data["max_seasonal_units"], int) and data["max_seasonal_units"] > 0
    assert isinstance(data["everyday_baseline_weekly_units"], int)
    assert data["everyday_baseline_weekly_units"] > 0
    assert isinstance(data["credit_balance_cents"], int)


def assert_retailer_commitment(data: dict) -> None:
    _assert_common(data, "RetailerCommitment")
    for field in ("program_id", "retailer_id", "product_id"):
        assert isinstance(data[field], str) and data[field], (
            f"RetailerCommitment.{field} must be a non-empty string"
        )
    assert isinstance(data["committed_units"], int) and data["committed_units"] > 0
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["reorder_units"], int) and data["reorder_units"] >= 0
    assert isinstance(data["reorder_used"], bool)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data.get("supersedes_commitment_id") is None or isinstance(
        data["supersedes_commitment_id"], str
    )
    _assert_iso(data.get("ship_window_open_on"), "ship_window_open_on", "RetailerCommitment")
    _assert_iso(data.get("ship_window_close_on"), "ship_window_close_on", "RetailerCommitment")
    assert data["status"] in {s.value for s in CommitmentStatus}


def assert_shipment(data: dict) -> None:
    _assert_common(data, "Shipment")
    assert isinstance(data["commitment_id"], str) and data["commitment_id"]
    assert isinstance(data["warehouse_id"], str) and data["warehouse_id"]
    assert isinstance(data["units"], int) and data["units"] > 0
    _assert_iso(data.get("ship_on"), "ship_on", "Shipment")
    assert isinstance(data["temp_controlled"], bool)
    assert isinstance(data["temp_control_declined_by_retailer"], bool)
    if data["status"] == ShipmentStatus.DELIVERED.value:
        _assert_iso(data.get("delivered_on"), "delivered_on", "Shipment")
    else:
        assert data.get("delivered_on") is None, (
            "delivered_on stays null until DELIVERED (PRD §3.6)"
        )
    assert data["status"] in {s.value for s in ShipmentStatus}


def assert_heat_claim(data: dict) -> None:
    _assert_common(data, "HeatClaim")
    assert isinstance(data["shipment_id"], str) and data["shipment_id"]
    assert isinstance(data["claimed_units"], int) and data["claimed_units"] >= 1
    assert data["reason"] in {r.value for r in HeatClaimReason}
    assert isinstance(data["evidence_note"], str)
    assert isinstance(data["auto_approve"], bool)
    if data["status"] == HeatClaimStatus.APPROVED.value:
        assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0, (
            "credit_cents is set on APPROVED (PRD §3.8)"
        )
    else:
        assert data.get("credit_cents") is None, (
            "credit_cents stays null until an approval sets it (PRD §3.8)"
        )
    assert data["status"] in {s.value for s in HeatClaimStatus}


def assert_warehouse(data: dict) -> None:
    _assert_common(data, "Warehouse")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["temp_controlled"], bool)
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["in_use_units"], int) and data["in_use_units"] >= 0
    assert isinstance(data["quarantined_units"], int) and data["quarantined_units"] >= 0
    assert data["quarantined_units"] <= data["in_use_units"], (
        "quarantined_units is a subset of in_use_units (PRD §2.9)"
    )
    assert data["posture"] in {p.value for p in WarehousePosture}


def assert_inventory_lot(data: dict) -> None:
    _assert_common(data, "InventoryLot")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["warehouse_id"], str) and data["warehouse_id"]
    assert isinstance(data["production_run_id"], str) and data["production_run_id"]
    assert isinstance(data["lot_code"], str) and data["lot_code"].startswith("LOT-"), (
        "lot_code is LOT- followed by a zero-padded monotone sequence (PRD §3.2)"
    )
    assert isinstance(data["units_on_hand"], int) and data["units_on_hand"] >= 0
    assert data["status"] in {s.value for s in InventoryLotStatus}


def assert_disposition_order(data: dict) -> None:
    _assert_common(data, "DispositionOrder")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["warehouse_id"], str) and data["warehouse_id"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["channel"] in {c.value for c in DispositionChannel}
    if data["channel"] == DispositionChannel.MARKDOWN.value:
        assert isinstance(data["markdown_pct"], (int, float)), (
            "MARKDOWN orders carry markdown_pct (PRD §3.9)"
        )
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    assert data.get("approved_by_user_id") is None or isinstance(
        data["approved_by_user_id"], str
    )
    if data["status"] == DispositionOrderStatus.EXECUTED.value:
        assert isinstance(data["recovered_value_cents"], int), (
            "recovered_value_cents is settled at execute (PRD §3.9)"
        )
    assert data["status"] in {s.value for s in DispositionOrderStatus}


def assert_commodity_contract(data: dict) -> None:
    _assert_common(data, "CommodityContract")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["commodity"] in {c.value for c in Commodity}
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] > 0
    assert isinstance(data["contract_price_cents_per_unit"], int)
    assert data["contract_price_cents_per_unit"] > 0
    assert isinstance(data["hedged_quantity_units"], int) and data["hedged_quantity_units"] >= 0
    assert data["hedged_quantity_units"] <= data["quantity_units"], (
        "hedged quantity may not exceed contracted quantity (PRD §3.3)"
    )
    if data["hedged_quantity_units"] > 0:
        assert isinstance(data["hedge_price_cents_per_unit"], int), (
            "a hedge strike is required whenever hedged_quantity_units > 0 (PRD §3.3)"
        )
    assert isinstance(data["provisional_spend_cents"], int)
    assert data.get("spot_price_cents_per_unit") is None or isinstance(
        data["spot_price_cents_per_unit"], int
    )
    assert data.get("effective_spend_cents") is None or isinstance(
        data["effective_spend_cents"], int
    )
    assert data["status"] in {s.value for s in CommodityContractStatus}


def assert_sell_through_report(data: dict) -> None:
    _assert_common(data, "SellThroughReport")
    assert isinstance(data["retailer_id"], str) and data["retailer_id"]
    assert isinstance(data["program_id"], str) and data["program_id"]
    _assert_iso(data.get("week_of_on"), "week_of_on", "SellThroughReport")
    for field in ("seasonal_units_sold", "seasonal_units_on_hand", "everyday_units_sold"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SellThroughReport.{field} must be a non-negative integer"
        )
    for field in ("cannibalization_raw", "cannibalization_adjusted"):
        assert isinstance(data[field], (int, float)), (
            f"SellThroughReport.{field} must be numeric"
        )


# ===========================================================================
# Domain invariant checkers
# ===========================================================================

def assert_warehouse_posture_consistent(data: dict) -> None:
    """PRD §2.9: posture must equal the value recomputed from the load figures
    with the inclusive 0.85-floor and capacity boundaries."""
    assert_warehouse(data)
    expected = expected_warehouse_posture(data["in_use_units"], data["capacity_units"])
    assert data["posture"] == expected, (
        f"Warehouse posture {data['posture']} != recomputed {expected} "
        f"(in_use={data['in_use_units']}, capacity={data['capacity_units']})"
    )


def assert_cannibalization_guard_inputs(raw_values, expect_blocked: bool) -> None:
    """PRD §3.9: with at least one report, MARKDOWN approve is blocked iff the
    average cannibalization_raw is below the 0.85 floor."""
    assert raw_values, "guard applies only when at least one report exists"
    average = sum(raw_values) / len(raw_values)
    if expect_blocked:
        assert average < CANNIBALIZATION_FLOOR
    else:
        assert average >= CANNIBALIZATION_FLOOR
