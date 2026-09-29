"""Entity assertions and domain invariant checkers for the S&OP surface."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccuracyGrade,
    AllocationPass,
    AllocationStatus,
    BiasFlag,
    ConsensusAdjustmentStatus,
    ConstraintType,
    CustomerChannel,
    CyclePosture,
    DemandForecastStatus,
    ForecastMethod,
    ItemLifecycleState,
    PlanningCycleStatus,
    PromotionStatus,
    ScenarioStatus,
    ScenarioType,
    SupplyPlanStatus,
    SupplyReviewPolicy,
)


def _assert_common_fields(data: dict, label: str) -> None:
    """id / created_at / updated_at / version, carried by every record except an
    accuracy record."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def _assert_two_dp(value, label: str) -> None:
    if value is None:
        return
    assert round(float(value), 2) == float(
        value
    ), f"{label} must carry at most two decimal places, got {value}"


def assert_product_family(data: dict) -> None:
    _assert_common_fields(data, "ProductFamily")
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["accountable_planner_user_id"], str)
    assert float(data["units_per_hour"]) > 0
    assert float(data["max_monthly_hours"]) > 0
    assert data["bias_flag"] in [f.value for f in BiasFlag]
    assert data["accuracy_grade"] in [g.value for g in AccuracyGrade]
    assert isinstance(data["scored_record_count"], int)
    _assert_two_dp(data.get("rolling_wmape_pct"), "ProductFamily.rolling_wmape_pct")
    _assert_two_dp(data.get("rolling_bias_pct"), "ProductFamily.rolling_bias_pct")


def assert_item(data: dict) -> None:
    _assert_common_fields(data, "Item")
    assert isinstance(data["sku"], str) and data["sku"]
    assert is_valid_uuid(data["family_id"])
    assert data["unit_price_cents"] > 0
    assert data["unit_cost_cents"] > 0
    assert data["on_hand_units"] >= 0
    assert data["material_supply_cap_units"] >= 0
    assert data["avg_monthly_demand_units"] >= 0
    assert 0 <= float(data["npi_ramp_pct"]) <= 200
    assert 0 < float(data["service_level_target_pct"]) <= 100
    assert 0 <= float(data["demand_cv"]) <= 3
    assert data["lead_time_days"] >= 1
    assert isinstance(data["safety_stock_units"], int)
    assert isinstance(data["reorder_point_units"], int)
    assert data["lifecycle_state"] in [s.value for s in ItemLifecycleState]


def assert_customer(data: dict) -> None:
    _assert_common_fields(data, "Customer")
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["channel"] in [c.value for c in CustomerChannel]
    assert data["priority_rank"] >= 1
    assert isinstance(data["credit_hold"], bool)


def assert_capacity_block(data: dict) -> None:
    _assert_common_fields(data, "CapacityBlock")
    assert is_valid_uuid(data["family_id"])
    assert data["end_date"] > data["start_date"], "end_date must be after start_date"
    assert float(data["available_hours"]) > 0


def assert_promotion(data: dict) -> None:
    _assert_common_fields(data, "Promotion")
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["end_month"] >= data["start_month"]
    assert 0 < float(data["lift_pct"]) <= 300
    assert 0 <= float(data["cannibalization_pct"]) <= 100
    assert data["status"] in [s.value for s in PromotionStatus]


def assert_planning_cycle(data: dict) -> None:
    _assert_common_fields(data, "PlanningCycle")
    assert isinstance(data["cycle_code"], str) and data["cycle_code"]
    assert data["horizon_end_month"] >= data["horizon_start_month"]
    assert data["financial_commitment_cents"] >= 0
    assert data["supply_review_policy"] in [p.value for p in SupplyReviewPolicy]
    assert data["status"] in [s.value for s in PlanningCycleStatus]
    assert data["posture"] in [p.value for p in CyclePosture]
    assert data["reopen_count"] >= 0
    assert data["plan_value_cents"] >= 0
    assert data["constrained_plan_count"] >= 0
    assert_cycle_money_conserved(data)
    assert_cycle_posture(data)


def assert_cycle_money_conserved(cycle: dict, selected_closure_cents=None) -> None:
    """residual_gap_cents == financial_commitment_cents - plan_value_cents -
    selected_closure_cents, with gross_gap_cents the intermediate figure."""
    expected_gross = cycle["financial_commitment_cents"] - cycle["plan_value_cents"]
    assert cycle["gross_gap_cents"] == expected_gross, (
        "gross_gap_cents must be financial_commitment_cents minus plan_value_cents, "
        f"expected {expected_gross}, got {cycle['gross_gap_cents']}"
    )
    closure = (
        cycle["selected_closure_cents"]
        if selected_closure_cents is None
        else selected_closure_cents
    )
    expected_residual = cycle["gross_gap_cents"] - closure
    assert cycle["residual_gap_cents"] == expected_residual, (
        "residual_gap_cents must be gross_gap_cents minus selected_closure_cents, "
        f"expected {expected_residual}, got {cycle['residual_gap_cents']}"
    )


def assert_cycle_posture(cycle: dict) -> None:
    """PUBLISHED wins first, then residual_gap_cents > 0 or
    constrained_plan_count >= 1, otherwise GREEN."""
    if cycle["status"] == PlanningCycleStatus.PUBLISHED.value:
        expected = CyclePosture.FROZEN.value
    elif cycle["residual_gap_cents"] > 0 or cycle["constrained_plan_count"] >= 1:
        expected = CyclePosture.AT_RISK.value
    else:
        expected = CyclePosture.GREEN.value
    assert cycle["posture"] == expected, (
        f"posture must be {expected} for status={cycle['status']}, "
        f"residual_gap_cents={cycle['residual_gap_cents']}, "
        f"constrained_plan_count={cycle['constrained_plan_count']}, "
        f"got {cycle['posture']}"
    )


def assert_demand_forecast(data: dict) -> None:
    _assert_common_fields(data, "DemandForecast")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["customer_id"])
    assert len(data["month"]) == 7 and data["month"][4] == "-"
    assert data["method"] in [m.value for m in ForecastMethod]
    assert data["status"] in [s.value for s in DemandForecastStatus]
    assert isinstance(data["baseline_units"], int)
    assert isinstance(data["consensus_units"], int)
    assert data["endorsed_adjustment_count"] >= 0


def assert_consensus_adjustment(data: dict) -> None:
    _assert_common_fields(data, "ConsensusAdjustment")
    assert is_valid_uuid(data["demand_forecast_id"])
    assert data["status"] in [s.value for s in ConsensusAdjustmentStatus]
    assert isinstance(data["applied_delta_units"], int)
    assert 0 <= data["revision_round"] <= 3
    assert isinstance(data["rationale"], str) and data["rationale"]
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_supply_plan(data: dict) -> None:
    _assert_common_fields(data, "SupplyPlan")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["item_id"])
    assert data["status"] in [s.value for s in SupplyPlanStatus]
    assert data["constraint_type"] in [c.value for c in ConstraintType]
    assert isinstance(data["requires_replan"], bool)
    for field in (
        "gross_requirement_units",
        "target_build_units",
        "available_units",
        "material_cap_units",
        "demand_side_units",
        "constrained_units",
        "shortfall_units",
        "unallocated_units",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative"
    expected_shortfall = max(data["demand_side_units"] - data["constrained_units"], 0)
    assert data["shortfall_units"] == expected_shortfall, (
        "shortfall_units must be demand_side_units minus constrained_units floored at "
        f"zero, expected {expected_shortfall}, got {data['shortfall_units']}"
    )


def assert_allocation(data: dict) -> None:
    _assert_common_fields(data, "Allocation")
    assert is_valid_uuid(data["supply_plan_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["allocation_status"] in [s.value for s in AllocationStatus]
    assert data["allocation_pass"] in [p.value for p in AllocationPass]
    assert data["requested_units"] >= 0
    assert data["allocated_units"] >= 0
    _assert_two_dp(data["fill_rate_pct"], "Allocation.fill_rate_pct")
    if data["requested_units"] == 0:
        assert float(data["fill_rate_pct"]) == 100.00, (
            "a row whose requested_units is 0 carries a fill_rate_pct of exactly "
            f"100.00, got {data['fill_rate_pct']}"
        )


def assert_allocation_units_conserved(plan: dict, allocations: list) -> None:
    """sum(allocated_units) + unallocated_units == constrained_units, with every
    row participating regardless of its allocation_status."""
    total = sum(row["allocated_units"] for row in allocations)
    assert total + plan["unallocated_units"] == plan["constrained_units"], (
        f"sum(allocated_units)={total} plus unallocated_units="
        f"{plan['unallocated_units']} must equal constrained_units="
        f"{plan['constrained_units']}"
    )


def assert_scenario(data: dict) -> None:
    _assert_common_fields(data, "Scenario")
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["scenario_type"] in [t.value for t in ScenarioType]
    assert data["status"] in [s.value for s in ScenarioStatus]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    for field in (
        "incremental_units",
        "gross_uplift_cents",
        "investment_cost_cents",
        "pre_trade_closure_cents",
        "trade_spend_cents",
        "net_gap_closure_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_scenario_closure_chain(data: dict) -> None:
    """pre_trade_closure_cents and net_gap_closure_cents are pure differences of
    the figures written before them."""
    expected_pre = data["gross_uplift_cents"] - data["investment_cost_cents"]
    assert data["pre_trade_closure_cents"] == expected_pre, (
        "pre_trade_closure_cents must be gross_uplift_cents minus "
        f"investment_cost_cents, expected {expected_pre}, got "
        f"{data['pre_trade_closure_cents']}"
    )
    expected_net = data["pre_trade_closure_cents"] - data["trade_spend_cents"]
    assert data["net_gap_closure_cents"] == expected_net, (
        "net_gap_closure_cents must be pre_trade_closure_cents minus "
        f"trade_spend_cents, expected {expected_net}, got "
        f"{data['net_gap_closure_cents']}"
    )


def assert_accuracy_record(data: dict) -> None:
    """An accuracy record carries only id and created_at — no updated_at and no
    version."""
    assert is_valid_uuid(data.get("id", "")), "AccuracyRecord.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "AccuracyRecord.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "AccuracyRecord has no updated_at field"
    assert "version" not in data, "AccuracyRecord has no version field"
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["actual_units"] >= 0
    assert data["abs_error_units"] >= 0
    assert (
        data["signed_error_units"] == data["forecast_units_snapshot"] - data["actual_units"]
    ), "signed_error_units must be forecast_units_snapshot minus actual_units"
    assert data["abs_error_units"] == abs(data["signed_error_units"])
    if data["actual_units"] == 0:
        assert data["ape_pct"] is None, "ape_pct is null when actual_units is 0"
    else:
        _assert_two_dp(data["ape_pct"], "AccuracyRecord.ape_pct")
    assert isinstance(data["accountable_planner_user_id"], str)


def assert_accuracy_summary(data: dict) -> None:
    assert data["record_count"] >= 0
    assert data["bias_flag"] in [f.value for f in BiasFlag]
    assert data["accuracy_grade"] in [g.value for g in AccuracyGrade]
    _assert_two_dp(data.get("mape_pct"), "mape_pct")
    _assert_two_dp(data.get("wmape_pct"), "wmape_pct")
    _assert_two_dp(data.get("bias_pct"), "bias_pct")
    assert data["total_actual_units"] >= 0
    assert data["total_abs_error_units"] >= 0


def assert_envelope_meta(body: dict) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta['api_request_id']}"
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int) -> None:
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] == (offset + limit < total_count)
