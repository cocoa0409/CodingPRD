"""Entity assertions and domain invariant checkers (PRD sections 2.5, 3.x).

assert_<entity>(data) validates the PRD-declared field surface of each resource.
expected_* helpers re-derive the PRD-pinned calculation results so tests assert
exact values rather than recomputing formulas inline.
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from . import constants as C
from .types import (
    AllocationStatus,
    AssemblerStatus,
    AssemblyJobStatus,
    Component,
    ConnectedDeviceStatus,
    CoverageDetermination,
    GrillModelStatus,
    InventoryLotStatus,
    PartsOrderStatus,
    PartSkuStatus,
    SaleStatus,
    SeasonStatus,
    ChannelType,
    ServiceTier,
    CertificationLevel,
    JobType,
    AccessoryType,
    FulfillmentType,
    AllocationAction,
    AssemblerAction,
    AssemblyJobAction,
    SaleAction,
    ClaimAction,
    PartAction,
    PartsOrderAction,
    FirmwareAction,
    ModelLifecycleAction,
    UserRole,
)


def round_half_up(value) -> int:
    """Commercial rounding: a fraction of one half or greater rounds away from zero (PRD 2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be a positive int"


def _assert_nullable_ts(data: dict, field: str, entity: str) -> None:
    assert field in data, f"{entity}.{field} must be present (null allowed)"
    if data[field] is not None:
        assert is_iso8601_timestamp(data[field]), f"{entity}.{field} must be ISO 8601 when set"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_season(data: dict) -> None:
    _assert_common_fields(data, "Season")
    for f in ("name", "build_start", "allocation_open", "in_season_start", "clearance_start", "season_end"):
        assert isinstance(data.get(f), str) and data[f], f"Season.{f} must be a non-empty string"
    for f in ("build_start", "allocation_open", "in_season_start", "clearance_start", "season_end"):
        assert is_iso8601_timestamp(data[f]), f"Season.{f} must be ISO 8601"
    assert isinstance(data.get("year"), int), "Season.year must be an integer"
    assert isinstance(data.get("demand_forecast_units"), int), "Season.demand_forecast_units must be an integer"
    assert data.get("status") in [s.value for s in SeasonStatus], f"Season.status unexpected: {data.get('status')}"


def assert_grill_model(data: dict) -> None:
    _assert_common_fields(data, "GrillModel")
    for f in ("model_code", "model_family", "current_firmware_version"):
        assert isinstance(data.get(f), str) and data[f], f"GrillModel.{f} must be a non-empty string"
    for f in ("model_year", "base_price_cents", "demand_share_bp", "burner_coverage_years",
              "grate_coverage_years", "electronics_coverage_years", "other_coverage_years",
              "parts_support_years"):
        assert isinstance(data.get(f), int), f"GrillModel.{f} must be an integer"
    assert 0 <= data["demand_share_bp"] <= C.BP_DENOMINATOR, "GrillModel.demand_share_bp must be 0..10000"
    assert data.get("status") in [s.value for s in GrillModelStatus], f"GrillModel.status unexpected: {data.get('status')}"
    _assert_nullable_ts(data, "discontinued_at", "GrillModel")
    _assert_nullable_ts(data, "support_obligation_until", "GrillModel")


def assert_channel_account(data: dict) -> None:
    _assert_common_fields(data, "ChannelAccount")
    assert isinstance(data.get("name"), str) and data["name"], "ChannelAccount.name must be a non-empty string"
    assert data.get("channel_type") in [t.value for t in ChannelType], f"ChannelAccount.channel_type unexpected: {data.get('channel_type')}"
    assert data.get("service_tier") in [t.value for t in ServiceTier], f"ChannelAccount.service_tier unexpected: {data.get('service_tier')}"
    for f in ("allocation_priority", "credit_limit_cents", "subsidy_bp", "outstanding_exposure_cents"):
        assert isinstance(data.get(f), int), f"ChannelAccount.{f} must be an integer"
    assert data["subsidy_bp"] == C.SUBSIDY_BP_BY_CHANNEL_TYPE[data["channel_type"]], (
        f"ChannelAccount.subsidy_bp must derive from channel_type: {data['channel_type']} -> "
        f"{C.SUBSIDY_BP_BY_CHANNEL_TYPE[data['channel_type']]}, got {data['subsidy_bp']}"
    )
    for f in ("accessory_attach_rate", "fuel_attach_rate"):
        assert isinstance(data.get(f), (int, float)), f"ChannelAccount.{f} must be numeric"
        assert 0.0 <= float(data[f]) <= 1.0, f"ChannelAccount.{f} must be within 0..1"


def assert_inventory_lot(data: dict) -> None:
    _assert_common_fields(data, "InventoryLot")
    for f in ("season_id", "model_id"):
        assert is_valid_uuid(data.get(f, "")), f"InventoryLot.{f} must be a UUID"
    assert isinstance(data.get("build_week"), str) and data["build_week"], "InventoryLot.build_week must be a non-empty string"
    for f in ("units_built", "units_available", "units_consumed"):
        assert isinstance(data.get(f), int), f"InventoryLot.{f} must be an integer"
    assert data["units_available"] >= 0 and data["units_consumed"] >= 0, "lot units must be non-negative"
    assert isinstance(data.get("recommended_build_forward_units"), int), "InventoryLot.recommended_build_forward_units must be an integer"
    assert "recommended_build_actual_units" in data, "InventoryLot.recommended_build_actual_units must be present (null allowed)"
    if data["recommended_build_actual_units"] is not None:
        assert isinstance(data["recommended_build_actual_units"], int), "InventoryLot.recommended_build_actual_units must be an integer when set"
    assert data.get("status") in [s.value for s in InventoryLotStatus], f"InventoryLot.status unexpected: {data.get('status')}"


def assert_allocation(data: dict) -> None:
    _assert_common_fields(data, "Allocation")
    for f in ("season_id", "channel_account_id", "model_id"):
        assert is_valid_uuid(data.get(f, "")), f"Allocation.{f} must be a UUID"
    for f in ("allocated_units", "committed_units"):
        assert isinstance(data.get(f), int) and data[f] >= 0, f"Allocation.{f} must be a non-negative integer"
    assert data["committed_units"] <= data["allocated_units"], (
        f"Allocation.committed_units ({data['committed_units']}) must not exceed allocated_units ({data['allocated_units']})"
    )
    assert data.get("status") in [s.value for s in AllocationStatus], f"Allocation.status unexpected: {data.get('status')}"
    assert is_iso8601_timestamp(data.get("offered_at", "")), "Allocation.offered_at must be ISO 8601"


def assert_assembler(data: dict) -> None:
    _assert_common_fields(data, "Assembler")
    assert isinstance(data.get("name"), str) and data["name"], "Assembler.name must be a non-empty string"
    assert data.get("certification_level") in [c.value for c in CertificationLevel], f"Assembler.certification_level unexpected: {data.get('certification_level')}"
    assert isinstance(data.get("service_regions"), list), "Assembler.service_regions must be a list"
    for f in ("max_concurrent_jobs", "active_job_count", "jobs_completed", "no_show_count"):
        assert isinstance(data.get(f), int) and data[f] >= 0, f"Assembler.{f} must be a non-negative integer"
    for f in ("no_show_history", "completion_history"):
        assert isinstance(data.get(f), list), f"Assembler.{f} must be a list"
        for ts in data[f]:
            assert is_iso8601_timestamp(ts), f"Assembler.{f} entries must be ISO 8601"
    for f in ("official_quality_bp", "provisional_quality_bp"):
        assert isinstance(data.get(f), int), f"Assembler.{f} must be an integer"
        assert 0 <= data[f] <= C.QUALITY_BASE_BP, f"Assembler.{f} must be clamped to 0..10000"
    assert data.get("status") in [s.value for s in AssemblerStatus], f"Assembler.status unexpected: {data.get('status')}"


def assert_assembly_job(data: dict) -> None:
    _assert_common_fields(data, "AssemblyJob")
    assert is_valid_uuid(data.get("sale_id", "")), "AssemblyJob.sale_id must be a UUID"
    assert "assembler_id" in data, "AssemblyJob.assembler_id must be present (null allowed)"
    if data["assembler_id"] is not None:
        assert is_valid_uuid(data["assembler_id"]), "AssemblyJob.assembler_id must be a UUID when set"
    assert data.get("job_type") in [t.value for t in JobType], f"AssemblyJob.job_type unexpected: {data.get('job_type')}"
    assert isinstance(data.get("distance_mi"), int) and data["distance_mi"] >= 0, "AssemblyJob.distance_mi must be a non-negative integer"
    assert isinstance(data.get("fee_cents"), int), "AssemblyJob.fee_cents must be an integer"
    _assert_nullable_ts(data, "window_start", "AssemblyJob")
    _assert_nullable_ts(data, "window_end", "AssemblyJob")
    assert data.get("status") in [s.value for s in AssemblyJobStatus], f"AssemblyJob.status unexpected: {data.get('status')}"


def assert_sale(data: dict) -> None:
    _assert_common_fields(data, "Sale")
    for f in ("season_id", "model_id", "channel_account_id"):
        assert is_valid_uuid(data.get(f, "")), f"Sale.{f} must be a UUID"
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1, "Sale.quantity must be a positive integer"
    assert isinstance(data.get("serials"), list), "Sale.serials must be a list"
    assert isinstance(data.get("accessories"), list), "Sale.accessories must be a list"
    assert isinstance(data.get("accessory_count"), int) and data["accessory_count"] == len(data["accessories"]), (
        "Sale.accessory_count must equal len(accessories)"
    )
    for f in ("has_cover", "has_tools", "has_fuel"):
        assert isinstance(data.get(f), bool), f"Sale.{f} must be a boolean"
    assert isinstance(data.get("unit_price_cents"), int) and data["unit_price_cents"] >= 0, "Sale.unit_price_cents must be a non-negative integer"
    assert data.get("status") in [s.value for s in SaleStatus], f"Sale.status unexpected: {data.get('status')}"
    assert is_iso8601_timestamp(data.get("sold_at", "")), "Sale.sold_at must be ISO 8601"
    _assert_nullable_ts(data, "registered_at", "Sale")


def assert_warranty_claim(data: dict) -> None:
    _assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("sale_id", "")), "WarrantyClaim.sale_id must be a UUID"
    assert data.get("component") in [c.value for c in Component], f"WarrantyClaim.component unexpected: {data.get('component')}"
    assert isinstance(data.get("failure_description"), str), "WarrantyClaim.failure_description must be a string"
    assert "serial_number" in data, "WarrantyClaim.serial_number must be present (null allowed)"
    assert is_iso8601_timestamp(data.get("claim_date", "")), "WarrantyClaim.claim_date must be ISO 8601"
    assert data.get("coverage_determination") in [d.value for d in CoverageDetermination], (
        f"WarrantyClaim.coverage_determination unexpected: {data.get('coverage_determination')}"
    )
    assert isinstance(data.get("goodwill"), bool), "WarrantyClaim.goodwill must be a boolean"
    for f in ("provisional_settlement_cents", "final_settlement_cents", "settlement_delta_cents"):
        assert f in data, f"WarrantyClaim.{f} must be present (null allowed)"
        if data[f] is not None:
            assert isinstance(data[f], int), f"WarrantyClaim.{f} must be an integer when set"
    assert "settlement_parts_order_id" in data, "WarrantyClaim.settlement_parts_order_id must be present (null allowed)"
    if data["settlement_parts_order_id"] is not None:
        assert is_valid_uuid(data["settlement_parts_order_id"]), "WarrantyClaim.settlement_parts_order_id must be a UUID when set"
    _assert_nullable_ts(data, "denied_at", "WarrantyClaim")
    assert data.get("status") in [s.value for s in WarrantyClaimStatus], f"WarrantyClaim.status unexpected: {data.get('status')}"


def assert_part_sku(data: dict) -> None:
    _assert_common_fields(data, "PartSku")
    assert isinstance(data.get("part_number"), str) and data["part_number"], "PartSku.part_number must be a non-empty string"
    assert data.get("component") in [c.value for c in Component], f"PartSku.component unexpected: {data.get('component')}"
    assert isinstance(data.get("compatible_model_codes"), list) and data["compatible_model_codes"], (
        "PartSku.compatible_model_codes must be a non-empty list"
    )
    assert isinstance(data.get("supersession_chain_id"), str) and data["supersession_chain_id"], (
        "PartSku.supersession_chain_id must be a non-empty string"
    )
    for f in ("chain_position", "unit_cost_cents", "stock_quantity"):
        assert isinstance(data.get(f), int), f"PartSku.{f} must be an integer"
    assert data["stock_quantity"] >= 0, "PartSku.stock_quantity must be non-negative"
    assert data.get("status") in [s.value for s in PartSkuStatus], f"PartSku.status unexpected: {data.get('status')}"


def assert_parts_order(data: dict) -> None:
    _assert_common_fields(data, "PartsOrder")
    for f in ("part_id", "sale_id", "resolved_part_id"):
        assert is_valid_uuid(data.get(f, "")), f"PartsOrder.{f} must be a UUID"
    assert "warranty_claim_id" in data, "PartsOrder.warranty_claim_id must be present (null allowed)"
    assert data.get("fulfillment_type") in [t.value for t in FulfillmentType], f"PartsOrder.fulfillment_type unexpected: {data.get('fulfillment_type')}"
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1, "PartsOrder.quantity must be a positive integer"
    assert isinstance(data.get("free_of_charge"), bool), "PartsOrder.free_of_charge must be a boolean"
    assert data["free_of_charge"] == (data["fulfillment_type"] in ("WARRANTY", "GOODWILL")), (
        "PartsOrder.free_of_charge must be true exactly for WARRANTY/GOODWILL"
    )
    assert isinstance(data.get("total_cost_cents"), int) and data["total_cost_cents"] >= 0, "PartsOrder.total_cost_cents must be a non-negative integer"
    assert isinstance(data.get("seq_no"), int) and data["seq_no"] >= 1, "PartsOrder.seq_no must be a positive integer"
    assert data.get("status") in [s.value for s in PartsOrderStatus], f"PartsOrder.status unexpected: {data.get('status')}"


def assert_connected_device(data: dict) -> None:
    _assert_common_fields(data, "ConnectedDevice")
    assert is_valid_uuid(data.get("sale_id", "")), "ConnectedDevice.sale_id must be a UUID"
    assert isinstance(data.get("app_account_id"), str) and data["app_account_id"], "ConnectedDevice.app_account_id must be a non-empty string"
    assert isinstance(data.get("pairing_token"), str) and data["pairing_token"], "ConnectedDevice.pairing_token must be a non-empty string"
    assert isinstance(data.get("firmware_version"), str) and data["firmware_version"], "ConnectedDevice.firmware_version must be a non-empty string"
    assert data.get("status") in [s.value for s in ConnectedDeviceStatus], f"ConnectedDevice.status unexpected: {data.get('status')}"


# ---------------------------------------------------------------------------
# Domain calc re-derivations (exact values pinned by PRD section 3)
# ---------------------------------------------------------------------------
def expected_provisional_settlement_cents(component: str) -> int:
    """PRD 3.7: catalog part cost plus fixed labor allowance for the component."""
    return C.PART_COST_CENTS[component] + C.LABOR_ALLOWANCE_CENTS[component]


def expected_final_settlement_cents(part_actual_cents: int, actual_labor_cents: int) -> int:
    """PRD 3.7: actual resolved part cost plus the supplied actual labor."""
    return part_actual_cents + actual_labor_cents


def expected_clearance_price_cents(
    base_price_cents: int,
    subsidy_bp: int,
    weeks_into_clearance: int,
    units_available: int,
    units_built: int,
) -> int:
    """PRD 3.5 clearance engine: tier by week index, coverage adjustment, cap,
    then the two pinned round-half-up steps (markdown first, subsidy second)."""
    if weeks_into_clearance >= C.TIER3_START_WEEK:
        tier_pct = C.TIER3_MARKDOWN_PCT
    elif weeks_into_clearance >= C.TIER2_START_WEEK:
        tier_pct = C.TIER2_MARKDOWN_PCT
    else:
        tier_pct = C.TIER1_MARKDOWN_PCT
    coverage_bp = (C.BP_DENOMINATOR * units_available) // max(units_built, 1)
    if coverage_bp >= C.COVERAGE_HIGH_BP:
        adj = C.OVERSTOCK_EXTRA_PCT
    elif coverage_bp <= C.COVERAGE_LOW_BP:
        adj = -C.UNDERSTOCK_RELIEF_PCT
    else:
        adj = 0
    markdown_pct = min(max(tier_pct + adj, 0), C.MAX_MARKDOWN_PCT)
    after_markdown = round_half_up(base_price_cents * (100 - markdown_pct) / 100)
    return round_half_up(after_markdown * (C.BP_DENOMINATOR - subsidy_bp) / C.BP_DENOMINATOR)


def expected_assembly_fee_cents(job_type: str, distance_mi: int, subsidy_bp: int) -> int:
    """PRD 3.6 fee engine: subsidy applied per component with round-half-up,
    then the rounded components summed (order is load-bearing)."""
    base = C.BASE_ASSEMBLY_FEE_CENTS
    surcharge = C.IN_HOME_SURCHARGE_CENTS if job_type == JobType.IN_HOME.value else 0
    travel = max(0, distance_mi - C.INCLUDED_MILES) * C.RATE_PER_MILE_CENTS if job_type == JobType.IN_HOME.value else 0

    def _discounted(component_cents: int) -> int:
        return round_half_up(component_cents * (C.BP_DENOMINATOR - subsidy_bp) / C.BP_DENOMINATOR)

    return _discounted(base) + _discounted(surcharge) + _discounted(travel)


def expected_official_quality_bp(no_show_count: int) -> int:
    """PRD 3.6 lifetime score: 10000 minus the per-no-show penalty, floored at 0."""
    return max(0, C.QUALITY_BASE_BP - C.NO_SHOW_PENALTY_BP * no_show_count)


def expected_provisional_quality_bp(recent_no_shows: int, recent_completions: int) -> int:
    """PRD 3.6 rolling score: penalty per recent no-show, bonus per recent
    completion, clamped into 0..10000."""
    raw = C.QUALITY_BASE_BP - C.NO_SHOW_PENALTY_BP * recent_no_shows + C.COMPLETION_BONUS_BP * recent_completions
    return min(max(raw, 0), C.QUALITY_BASE_BP)


def expected_attach_rate(numerator: int, denominator: int) -> float:
    """PRD 3.5 attach rates: 4 decimal places, round half up; empty denominator is exactly 0.0000."""
    if denominator == 0:
        return 0.0
    return float(Decimal(numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def expected_consumption_rate_bp(committed_units: int, allocated_units: int) -> int:
    """PRD 3.4 waterfall rate: floor of 10000 times committed over allocated."""
    return (C.BP_DENOMINATOR * committed_units) // allocated_units


def expected_forward_build_units(base_units: int, demand_share_bp: int) -> int:
    """PRD 3.3 forward sizing: floor of base x 11000/10000 x demand_share_bp/10000."""
    return (base_units * C.GROWTH_BP // C.BP_DENOMINATOR) * demand_share_bp // C.BP_DENOMINATOR


def expected_actual_build_units(units_consumed: int, weeks_elapsed: int) -> int:
    """PRD 3.3 actual sizing: floor of units_consumed x 26 / max(weeks_elapsed, 1)."""
    return (units_consumed * C.SEASON_WEEKS) // max(weeks_elapsed, 1)


def assert_lot_units_conserved(lot: dict, allocations: list) -> None:
    """PRD 3.3 availability derivation restated as conservation:
    units_built == units_available
      + sum(allocated_units over OFFERED/ACCEPTED/PARTIALLY_CONSUMED/CONSUMED)
      + sum(committed_units over RELEASED/EXPIRED/SUPERSEDED)."""
    active_states = {"OFFERED", "ACCEPTED", "PARTIALLY_CONSUMED", "CONSUMED"}
    inactive_states = {"RELEASED", "EXPIRED", "SUPERSEDED"}
    reserved = sum(a["allocated_units"] for a in allocations if a["status"] in active_states)
    committed_gone = sum(a["committed_units"] for a in allocations if a["status"] in inactive_states)
    assert lot["units_available"] + reserved + committed_gone == lot["units_built"], (
        f"lot units not conserved: available {lot['units_available']} + reserved {reserved} "
        f"+ committed-inactive {committed_gone} != built {lot['units_built']}"
    )


__all__ = [
    "round_half_up",
    "assert_season",
    "assert_grill_model",
    "assert_channel_account",
    "assert_inventory_lot",
    "assert_allocation",
    "assert_assembler",
    "assert_assembly_job",
    "assert_sale",
    "assert_warranty_claim",
    "assert_part_sku",
    "assert_parts_order",
    "assert_connected_device",
    "expected_provisional_settlement_cents",
    "expected_final_settlement_cents",
    "expected_clearance_price_cents",
    "expected_assembly_fee_cents",
    "expected_official_quality_bp",
    "expected_provisional_quality_bp",
    "expected_attach_rate",
    "expected_consumption_rate_bp",
    "expected_forward_build_units",
    "expected_actual_build_units",
    "assert_lot_units_conserved",
]
