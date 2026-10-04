"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>(data)`` validates the common system fields (PRD §2.5)
plus the presence and type of the entity's own fields. Invariant checkers
re-derive the PRD's pinned formulas and compare them against server-returned
state.
"""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    PHASE_WEIGHT_GATE_FAILED,
    PHASE_WEIGHT_GATE_PASSED,
    PHASE_WEIGHT_PENDING,
    RISK_AT_RISK_MIN_SCORE,
    RISK_DELIST_MIN_SCORE,
    RISK_WATCH_MIN_SCORE,
)
from .types import (
    AdvisoryScope,
    AnalysisStatus,
    Channel,
    DeductionBucket,
    DeductionStatus,
    EventStatus,
    EventType,
    ForecastCommitStatus,
    ForecastPubStatus,
    LaunchStatus,
    PhaseStatus,
    PhaseType,
    PlanStatus,
    PricePackStatus,
    RetailerStatus,
    ReviewDecision,
    ReviewStatus,
    RiskPosture,
    ShelfRecStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an int >= 1, got {data.get('version')!r}"
    )


def _values(enum_cls) -> list:
    return [m.value for m in enum_cls]


def assert_retailer(data: dict):
    _assert_common(data, "Retailer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["channels"], list) and len(data["channels"]) > 0
    assert len(set(data["channels"])) == len(data["channels"]), "channels must be duplicate-free"
    assert all(c in _values(Channel) for c in data["channels"])
    assert data["status"] in _values(RetailerStatus)


def assert_category(data: dict):
    _assert_common(data, "Category")
    assert isinstance(data["name"], str) and data["name"]
    assert data["advisory_scope"] in _values(AdvisoryScope)


def assert_plan(data: dict):
    _assert_common(data, "JointBusinessPlan")
    assert is_valid_uuid(data.get("retailer_id", "")), "retailer_id must be a UUID"
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be a UUID"
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["growth_target_pct"], (int, float))
    assert isinstance(data["weekly_baseline_cases"], int) and data["weekly_baseline_cases"] > 0
    assert isinstance(data["avg_unit_net_price_cents"], int) and data["avg_unit_net_price_cents"] > 0
    assert data["status"] in _values(PlanStatus)
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1
    assert "committed_growth_pct" in data, "committed_growth_pct key must be present (null until ACTIVATED)"
    assert "activated_at" in data, "activated_at key must be present (null until ACTIVATED)"
    if data["status"] == PlanStatus.ACTIVATED.value:
        assert data["committed_growth_pct"] is not None
        assert data["activated_at"] is not None
        assert is_iso8601_timestamp(data["activated_at"])


def assert_promotional_event(data: dict):
    _assert_common(data, "PromotionalEvent")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["event_type"] in _values(EventType)
    assert is_iso8601_timestamp(data.get("start_date", "")), "start_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_date", "")), "end_date must be ISO 8601"
    assert isinstance(data["discount_depth_pct"], (int, float))
    assert data["status"] in _values(EventStatus)
    assert "estimated_cost_cents" in data, "estimated_cost_cents key must be present (null while PENCILED)"
    if data["status"] == EventStatus.LOCKED.value:
        assert isinstance(data["estimated_cost_cents"], int)


def assert_category_analysis(data: dict):
    _assert_common(data, "CategoryAnalysis")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["period_label"], str)
    assert isinstance(data["includes_competitor_data"], bool)
    assert isinstance(data["total_category_growth_pct"], (int, float))
    assert isinstance(data["manufacturer_share_pct"], (int, float))
    # competitor_share_pct is derived as 100 - manufacturer_share_pct (PRD §3.3)
    assert data["competitor_share_pct"] == pytest.approx(100 - data["manufacturer_share_pct"], abs=1e-6)
    assert data["status"] in _values(AnalysisStatus)


def assert_shelf_recommendation(data: dict):
    _assert_common(data, "ShelfRecommendation")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["space_change_pct"], (int, float))
    assert isinstance(data["target_store_count"], int)
    assert isinstance(data["sku_adds"], list)
    assert isinstance(data["sku_drops"], list)
    assert data["status"] in _values(ShelfRecStatus)
    assert "accepted_at" in data, "accepted_at key must be present (null until accepted)"
    assert "verified_store_count" in data, "verified_store_count key must be present (null until VERIFIED)"
    if data["status"] in (
        ShelfRecStatus.IMPLEMENTING.value,
        ShelfRecStatus.VERIFIED.value,
        ShelfRecStatus.STALLED.value,
    ):
        assert data["accepted_at"] is not None
        assert is_iso8601_timestamp(data["accepted_at"])
    if data["status"] == ShelfRecStatus.VERIFIED.value:
        assert isinstance(data["verified_store_count"], int)


def assert_innovation_launch(data: dict):
    _assert_common(data, "InnovationLaunch")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["pack_family"], str) and data["pack_family"]
    assert is_iso8601_timestamp(data.get("launch_date", "")), "launch_date must be ISO 8601"
    assert isinstance(data["total_trade_budget_cents"], int) and data["total_trade_budget_cents"] > 0
    assert data["status"] in _values(LaunchStatus)
    assert isinstance(data["budget_remaining_cents"], int)
    assert isinstance(data["projected_distribution_weighted_pct"], (int, float))
    assert isinstance(data["projected_distribution_committed_pct"], (int, float))
    assert "launched_at" in data, "launched_at key must be present (null until LAUNCHED)"
    if data["status"] in (
        LaunchStatus.LAUNCHED.value,
        LaunchStatus.REVIEWED.value,
        LaunchStatus.DELISTED.value,
    ):
        assert data["launched_at"] is not None
        assert is_iso8601_timestamp(data["launched_at"])


def assert_launch_phase(data: dict):
    _assert_common(data, "LaunchPhase")
    assert is_valid_uuid(data.get("launch_id", "")), "launch_id must be a UUID"
    assert isinstance(data["phase_index"], int) and data["phase_index"] in (1, 2, 3, 4)
    assert data["phase_type"] in _values(PhaseType)
    assert isinstance(data["distribution_target_pct"], (int, float))
    assert isinstance(data["capacity_cases"], int)
    assert isinstance(data["trade_spend_cents"], int)
    assert data["status"] in _values(PhaseStatus)


def assert_trade_fund(data: dict):
    _assert_common(data, "TradeFund")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert isinstance(data["accrual_rate_pct"], (int, float))
    assert isinstance(data["edlp_split_pct"], int)
    for field in (
        "edlp_accrued_cents",
        "event_accrued_cents",
        "edlp_cash_cents",
        "event_cash_cents",
        "event_reserved_cents",
        "edlp_settled_cents",
        "event_settled_cents",
        "total_invoiced_cents",
        "edlp_available_cents",
        "event_available_cents",
    ):
        assert isinstance(data[field], int), f"TradeFund.{field} must be int cents, got {data.get(field)!r}"


def assert_deduction(data: dict):
    _assert_common(data, "Deduction")
    assert is_valid_uuid(data.get("fund_id", "")), "fund_id must be a UUID"
    assert isinstance(data["claim_reference"], str) and data["claim_reference"]
    assert data["bucket"] in _values(DeductionBucket)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in _values(DeductionStatus)
    assert "settled_amount_cents" in data, "settled_amount_cents key must be present (null before resolution)"
    assert isinstance(data["short_paid"], bool)
    assert isinstance(data["absorbed_by_manufacturer"], bool)
    if data["status"] in (DeductionStatus.SETTLED.value, DeductionStatus.WRITTEN_OFF.value):
        assert isinstance(data["settled_amount_cents"], int)
        assert data["short_paid"] == (data["settled_amount_cents"] < data["amount_cents"])
    if data["status"] == DeductionStatus.WRITTEN_OFF.value:
        assert data["absorbed_by_manufacturer"] is True


def assert_forecast(data: dict):
    _assert_common(data, "Forecast")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert is_iso8601_timestamp(data.get("week_start", "")), "week_start must be ISO 8601"
    assert isinstance(data["baseline_cases"], int) and data["baseline_cases"] > 0
    assert data["pub_status"] in _values(ForecastPubStatus)
    assert data["commit_status"] in _values(ForecastCommitStatus)
    assert "committed_cases" in data, "committed_cases key must be present (null while UNCOMMITTED)"
    assert "committed_at" in data, "committed_at key must be present (null while UNCOMMITTED)"
    if data["commit_status"] == ForecastCommitStatus.COMMITTED.value:
        assert isinstance(data["committed_cases"], int) and data["committed_cases"] > 0
        assert data["committed_at"] is not None
        assert is_iso8601_timestamp(data["committed_at"])


def assert_price_pack_decision(data: dict):
    _assert_common(data, "PricePackDecision")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert data["channel"] in _values(Channel)
    assert isinstance(data["pack_family"], str) and data["pack_family"]
    assert isinstance(data["pack_code"], str) and data["pack_code"]
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    # price_per_unit_cents = ceil(list_price_cents / unit_count) (PRD §3.8)
    expected_ppu = -(-data["list_price_cents"] // data["unit_count"])
    assert data["price_per_unit_cents"] == expected_ppu, (
        f"price_per_unit_cents must be ceil({data['list_price_cents']}/{data['unit_count']}) "
        f"= {expected_ppu}, got {data['price_per_unit_cents']}"
    )
    assert data["status"] in _values(PricePackStatus)


def assert_performance_review(data: dict):
    _assert_common(data, "PerformanceReview")
    assert is_valid_uuid(data.get("launch_id", "")), "launch_id must be a UUID"
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data["actual_sales_cents"], int) and data["actual_sales_cents"] >= 0
    assert isinstance(data["sales_target_cents"], int) and data["sales_target_cents"] > 0
    assert isinstance(data["target_distribution_pct"], (int, float))
    assert isinstance(data["distribution_achieved_pct"], (int, float))
    assert isinstance(data["sales_attainment_pct"], (int, float))
    assert isinstance(data["forecast_bias_pct"], (int, float))
    assert isinstance(data["friction_count"], int) and data["friction_count"] >= 0
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["risk_posture"] in _values(RiskPosture)
    assert data["status"] in _values(ReviewStatus)
    assert "decision" in data, "decision key must be present (null until FINALIZED)"
    if data["status"] == ReviewStatus.FINALIZED.value:
        assert data["decision"] in _values(ReviewDecision)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_fund_invariants(fund: dict):
    """Derived-availability invariants (PRD §2.11): availability is derived,
    never stored inconsistently.

    edlp_available_cents  == edlp_accrued_cents - edlp_settled_cents
    event_available_cents == event_accrued_cents - event_reserved_cents - event_settled_cents
    """
    assert fund["edlp_available_cents"] == fund["edlp_accrued_cents"] - fund["edlp_settled_cents"], (
        f"EDLP availability mismatch: {fund['edlp_available_cents']} != "
        f"{fund['edlp_accrued_cents']} - {fund['edlp_settled_cents']}"
    )
    assert fund["event_available_cents"] == (
        fund["event_accrued_cents"] - fund["event_reserved_cents"] - fund["event_settled_cents"]
    ), (
        f"EVENT availability mismatch: {fund['event_available_cents']} != "
        f"{fund['event_accrued_cents']} - {fund['event_reserved_cents']} - {fund['event_settled_cents']}"
    )


def assert_launch_budget_invariant(launch: dict, phases: list):
    """Conserved launch budget: total == remaining + sum(phase trade_spend_cents)."""
    spent = sum(p["trade_spend_cents"] for p in phases)
    assert launch["budget_remaining_cents"] == launch["total_trade_budget_cents"] - spent, (
        f"budget_remaining_cents {launch['budget_remaining_cents']} != "
        f"{launch['total_trade_budget_cents']} - {spent}"
    )


def _round_half_up_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _phase_weight(status: str) -> Decimal:
    if status == PhaseStatus.GATE_PASSED.value:
        return Decimal(str(PHASE_WEIGHT_GATE_PASSED))
    if status == PhaseStatus.PENDING.value:
        return Decimal(str(PHASE_WEIGHT_PENDING))
    return Decimal(str(PHASE_WEIGHT_GATE_FAILED))


def assert_distribution_projections(launch: dict, phases: list):
    """Recompute both distribution projections from phase data (PRD §3.5) and
    compare to the launch's stored fields, both rounded half-up to 2 dp.

    committed: sum(target * 1.0) over GATE_PASSED phases, 0.0 otherwise.
    weighted:  sum(target * weight) with weights 1.0 / 0.25 / 0.0.
    """
    committed = Decimal("0")
    weighted = Decimal("0")
    for p in phases:
        target = Decimal(str(p["distribution_target_pct"]))
        if p["status"] == PhaseStatus.GATE_PASSED.value:
            committed += target
        weighted += target * _phase_weight(p["status"])
    expected_committed = _round_half_up_2dp(committed)
    expected_weighted = _round_half_up_2dp(weighted)
    assert launch["projected_distribution_committed_pct"] == pytest.approx(
        float(expected_committed), abs=0.001
    ), (
        f"projected_distribution_committed_pct {launch['projected_distribution_committed_pct']} "
        f"!= {expected_committed}"
    )
    assert launch["projected_distribution_weighted_pct"] == pytest.approx(
        float(expected_weighted), abs=0.001
    ), (
        f"projected_distribution_weighted_pct {launch['projected_distribution_weighted_pct']} "
        f"!= {expected_weighted}"
    )


def expected_risk_posture(risk_score: int) -> str:
    """The PRD §3.9 posture ladder read straight off the score."""
    if risk_score >= RISK_DELIST_MIN_SCORE:
        return RiskPosture.DELIST_RECOMMENDED.value
    if risk_score >= RISK_AT_RISK_MIN_SCORE:
        return RiskPosture.AT_RISK.value
    if risk_score >= RISK_WATCH_MIN_SCORE:
        return RiskPosture.WATCH.value
    return RiskPosture.HEALTHY.value


def assert_risk_posture_matches_score(review: dict):
    """risk_posture must be the threshold read of risk_score (PRD §3.9)."""
    assert review["risk_posture"] == expected_risk_posture(review["risk_score"]), (
        f"risk_posture {review['risk_posture']} inconsistent with risk_score {review['risk_score']}"
    )
