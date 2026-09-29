"""Entity shape assertions and domain invariant checkers."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C
from .api_client import canonical_iso
from .types import (
    CATEGORY_TOTAL_FIELD,
    AttainmentStatus,
    CandidateStatus,
    Category,
    DataState,
    Posture,
    ReportStatus,
    ValuationBasis,
)

_MONEY_FIELDS = (
    "authorized_budget_cents",
    "budget_available_cents",
    "cash_and_inkind_cents",
    "charges_cents",
    "community_building_cents",
    "community_health_improvement_cents",
    "direct_cost_cents",
    "financial_assistance_cents",
    "funded_cents",
    "funding_cents",
    "grand_total_cents",
    "indirect_allocation_cents",
    "pledged_cents",
    "subsidized_services_cents",
    "total_operating_expense_cents",
    "total_valued_cents",
    "valued_cents",
)

_BASIS_POINT_FIELDS = ("committed_fte_bp", "fte_bp", "fte_capacity_bp")


# --------------------------------------------------------------------------
# Common shape
# --------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """``id``, ``created_at``, ``updated_at`` and ``version`` on every record.

    ``id`` is a bare server-minted UUID with no type prefix; the two timestamps
    are ISO 8601 UTC instants; ``version`` starts at 1 and increments by exactly
    1 on every mutation.
    """
    assert "id" in entity, "record is missing its id"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    for field in ("created_at", "updated_at"):
        assert field in entity, f"record is missing {field}"
        assert is_iso8601_timestamp(entity[field]), f"{field} is not ISO 8601: {entity[field]!r}"
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_money_is_integer_cents(entity: Dict[str, Any]) -> None:
    """Every monetary and basis-point field is an integer, never a string."""
    for field in _MONEY_FIELDS + _BASIS_POINT_FIELDS:
        if field in entity and entity[field] is not None:
            assert isinstance(entity[field], int) and not isinstance(entity[field], bool), (
                f"{field} must be an integer, got {type(entity[field]).__name__}: {entity[field]!r}"
            )


def assert_timestamps_equal(left: Optional[str], right: Optional[str], label: str = "") -> None:
    """Compare two instants after canonicalising fractional-second width."""
    assert canonical_iso(left) == canonical_iso(right), (
        f"{label or 'timestamps'} differ: {left!r} vs {right!r}"
    )


def assert_no_mutation(before: Dict[str, Any], after: Dict[str, Any], label: str = "record") -> None:
    """A rejected operation changes nothing and increments no ``version``."""
    assert after["version"] == before["version"], (
        f"{label} version moved from {before['version']} to {after['version']} "
        "but the operation was rejected"
    )
    assert canonical_iso(after["updated_at"]) == canonical_iso(before["updated_at"]), (
        f"{label} updated_at moved but the operation was rejected"
    )


def round_half_up(value: float, places: int = 2) -> float:
    """Round half up to ``places`` decimals, the method the PRD pins."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_close(actual: Any, expected: float, label: str = "value") -> None:
    """Exact comparison at two decimal places for a rounded domain figure."""
    assert actual is not None, f"{label} is null"
    assert round_half_up(float(actual)) == round_half_up(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_cycle(cycle: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(cycle)
    assert_money_is_integer_cents(cycle)
    for counter in (
        "sufficient_indicator_count",
        "completed_interview_count",
        "selected_priority_count",
        "review_flag_count",
        "board_deferral_count",
        "mid_cycle_adjustment_count",
        "annual_report_count",
    ):
        assert isinstance(cycle.get(counter), int), f"cycle counter {counter} must be an integer"
    assert cycle["posture"] in (Posture.OPEN, Posture.RESTRICTED, Posture.FROZEN)
    assert isinstance(cycle.get("public_availability_met"), bool)
    _assert_expected(cycle, expected, "cycle")


def assert_indicator(indicator: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(indicator)
    assert indicator["data_state"] in (DataState.SUFFICIENT, DataState.INSUFFICIENT)
    assert isinstance(indicator.get("subgroup_count"), int)
    assert isinstance(indicator.get("evidence_count"), int)
    _assert_expected(indicator, expected, "indicator")


def assert_data_point(data_point: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(data_point)
    _assert_expected(data_point, expected, "data point")


def assert_party(party: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(party)
    assert_money_is_integer_cents(party)
    _assert_expected(party, expected, "party")


def assert_interview(interview: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(interview)
    _assert_expected(interview, expected, "interview")


def assert_candidate(candidate: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(candidate)
    assert isinstance(candidate.get("concern_input_dirty"), bool)
    assert isinstance(candidate.get("strategy_count"), int)
    _assert_expected(candidate, expected, "candidate")


def assert_strategy(strategy: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(strategy)
    assert_money_is_integer_cents(strategy)
    assert isinstance(strategy.get("active_objective_count"), int)
    _assert_expected(strategy, expected, "strategy")


def assert_objective(objective: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(objective)
    assert objective["attainment_status"] in (
        AttainmentStatus.PENDING,
        AttainmentStatus.NOT_MET,
        AttainmentStatus.PARTIAL,
        AttainmentStatus.MET,
    )
    _assert_expected(objective, expected, "objective")


def assert_agreement(agreement: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(agreement)
    assert_money_is_integer_cents(agreement)
    _assert_expected(agreement, expected, "agreement")


def assert_commitment(commitment: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(commitment)
    assert_money_is_integer_cents(commitment)
    _assert_expected(commitment, expected, "commitment")


def assert_report(report: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(report)
    assert_money_is_integer_cents(report)
    assert report["status"] in (ReportStatus.OPEN, ReportStatus.LOCKED, ReportStatus.FILED)
    assert report["valuation_basis"] in (ValuationBasis.PROVISIONAL, ValuationBasis.FINAL)
    _assert_expected(report, expected, "report")


def assert_posting(posting: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(posting)
    assert_money_is_integer_cents(posting)
    _assert_expected(posting, expected, "posting")


def assert_evaluation(evaluation: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(evaluation)
    assert isinstance(evaluation.get("objectives_revised_count"), int)
    _assert_expected(evaluation, expected, "evaluation")


def _assert_expected(entity: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for field, want in expected.items():
        assert field in entity, f"{label} is missing {field}"
        got = entity[field]
        if isinstance(want, float):
            assert_close(got, want, f"{label}.{field}")
        else:
            assert got == want, f"{label}.{field}: expected {want!r}, got {got!r}"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def expected_severity_score(overall_value: float, benchmark_value: float) -> float:
    """Rate over benchmark times 50, rounded to 2 dp, then capped at 100.00.

    The cap is applied after the rounding, never before.
    """
    raw = round_half_up(overall_value / benchmark_value * C.BENCHMARK_PARITY_MULTIPLIER)
    return min(raw, C.SEVERITY_SCORE_CEILING)


def expected_disparity_points(disparity_ratio: Optional[float]) -> float:
    """0.00 when the ratio is null; otherwise (ratio - 1) * 100, capped at 100.00."""
    if disparity_ratio is None:
        return 0.00
    raw = round_half_up((disparity_ratio - 1) * 100)
    return min(raw, C.DISPARITY_POINTS_CEILING)


def expected_concern_index(sessions: Any) -> float:
    """Attendance-weighted mean rating times 20, rounded exactly once.

    ``sessions`` is an iterable of ``(rating, attendee_count)`` pairs.
    """
    pairs = list(sessions)
    weighted = sum(rating * attendees for rating, attendees in pairs)
    attendance = sum(attendees for _rating, attendees in pairs)
    return round_half_up(weighted / attendance * C.CONCERN_SCALE_MULTIPLIER)


def expected_composite_score(
    severity: float, disparity: float, concern: float, capacity: float, variant_weights: Dict[str, float]
) -> float:
    """A single round-half-up applied to the finished weighted sum."""
    total = (
        severity * variant_weights["severity"]
        + disparity * variant_weights["disparity"]
        + concern * variant_weights["concern"]
        + capacity * variant_weights["capacity"]
    )
    return round_half_up(total)


def expected_charge_based_valuation(charges_cents: int, ratio: float) -> int:
    """Charges times the ratio, rounded half up to a whole number of cents."""
    return int(
        Decimal(charges_cents * Decimal(str(ratio))).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


def expected_overhead_rate(total_valued_cents: int) -> float:
    """Tier boundaries belong to the higher tier."""
    if total_valued_cents >= C.OVERHEAD_TIER_2_CEILING_CENTS:
        return C.OVERHEAD_RATE_TIER_3
    if total_valued_cents >= C.OVERHEAD_TIER_1_CEILING_CENTS:
        return C.OVERHEAD_RATE_TIER_2
    return C.OVERHEAD_RATE_TIER_1


def expected_indirect_allocation(total_valued_cents: int) -> int:
    rate = expected_overhead_rate(total_valued_cents)
    return int(
        Decimal(total_valued_cents * Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


def expected_benefit_pct(grand_total_cents: int, total_operating_expense_cents: int) -> float:
    return round_half_up(grand_total_cents / total_operating_expense_cents * 100)


def expected_attainment_pct(baseline: float, target: float, actual: float) -> float:
    """Rounded first, then clamped into 0.00 .. 150.00."""
    if target == baseline:
        return 100.00 if actual >= target else 0.00
    raw = round_half_up((actual - baseline) / (target - baseline) * 100)
    return min(max(raw, C.ATTAINMENT_FLOOR), C.ATTAINMENT_CEILING)


def expected_attainment_status(attainment_pct: float) -> str:
    """Three inclusive bands; exactly 100.00 is MET and exactly 50.00 is PARTIAL."""
    if attainment_pct >= C.ATTAINMENT_MET_THRESHOLD:
        return AttainmentStatus.MET
    if attainment_pct >= C.ATTAINMENT_PARTIAL_THRESHOLD:
        return AttainmentStatus.PARTIAL
    return AttainmentStatus.NOT_MET


def assert_report_totals(
    report: Dict[str, Any],
    total_operating_expense_cents: int = C.TOTAL_OPERATING_EXPENSE_CENTS,
    **category_totals: int,
) -> None:
    """Check the five category totals and every figure derived from them.

    ``total_valued_cents`` is the sum of the five category totals, the overhead
    tier is selected from that base, ``grand_total_cents`` is the base plus the
    allocation, and ``benefit_pct_of_expense`` is the grand total over the
    cycle's total operating expense times 100.
    """
    expected_by_field = {field: 0 for field in CATEGORY_TOTAL_FIELD.values()}
    for category, amount in category_totals.items():
        field = CATEGORY_TOTAL_FIELD.get(category, category)
        assert field in expected_by_field, f"unknown category total {category!r}"
        expected_by_field[field] = amount
    for field, want in expected_by_field.items():
        assert report[field] == want, f"report.{field}: expected {want}, got {report[field]}"

    base = sum(expected_by_field.values())
    assert report["total_valued_cents"] == base, (
        f"total_valued_cents: expected {base}, got {report['total_valued_cents']}"
    )
    assert_close(report["overhead_rate"], expected_overhead_rate(base), "overhead_rate")
    indirect = expected_indirect_allocation(base)
    assert report["indirect_allocation_cents"] == indirect, (
        f"indirect_allocation_cents: expected {indirect}, got {report['indirect_allocation_cents']}"
    )
    grand = base + indirect
    assert report["grand_total_cents"] == grand, (
        f"grand_total_cents: expected {grand}, got {report['grand_total_cents']}"
    )
    assert_close(
        report["benefit_pct_of_expense"],
        expected_benefit_pct(grand, total_operating_expense_cents),
        "benefit_pct_of_expense",
    )


def assert_budget_identity(strategy: Dict[str, Any], encumbered_cents: int) -> None:
    """``budget_available_cents`` plus the encumbered sum equals the authorized envelope."""
    assert strategy["budget_available_cents"] + encumbered_cents == strategy[
        "authorized_budget_cents"
    ], (
        "budget identity broken: available "
        f"{strategy['budget_available_cents']} + encumbered {encumbered_cents} != authorized "
        f"{strategy['authorized_budget_cents']}"
    )


def assert_posture(cycle: Dict[str, Any], expected: str) -> None:
    assert cycle["posture"] == expected, (
        f"posture: expected {expected}, got {cycle['posture']} "
        f"(status={cycle.get('status')}, review_flag_count={cycle.get('review_flag_count')})"
    )


def assert_score_fields_null(candidate: Dict[str, Any]) -> None:
    """A score-invalidated candidate keeps none of its four score snapshots."""
    assert candidate["status"] == CandidateStatus.SCORE_INVALIDATED
    for field in ("composite_score", "severity_input", "disparity_points", "community_concern_index"):
        assert candidate[field] is None, f"{field} should be null, got {candidate[field]!r}"


def assert_charge_based_posting(posting: Dict[str, Any], charges_cents: int, ratio: float) -> None:
    """A charge-based posting stores the ratio it used and the rounded product."""
    assert posting["category"] in (Category.FINANCIAL_ASSISTANCE, Category.SUBSIDIZED_SERVICES)
    expected = expected_charge_based_valuation(charges_cents, ratio)
    assert posting["valued_cents"] == expected, (
        f"valued_cents: expected {expected}, got {posting['valued_cents']}"
    )
    assert_close(posting["ratio_applied"], ratio, "ratio_applied")


def assert_cost_based_posting(posting: Dict[str, Any], direct_cost_cents: int) -> None:
    """A cost-based posting takes its cost unchanged and records no ratio."""
    assert posting["valued_cents"] == direct_cost_cents, (
        f"valued_cents: expected {direct_cost_cents}, got {posting['valued_cents']}"
    )
    assert posting["ratio_applied"] is None, (
        f"ratio_applied must be null on a cost-based posting, got {posting['ratio_applied']!r}"
    )
