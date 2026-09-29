"""Entity-shape and domain-invariant assertions (PRD §2.4, §2.6, §3).

Every checker here only asserts what PRD.md declares: the presence of the
common fields, the numeric precision of each declared field, and the
conservation identities the PRD states in words.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import MARGIN_FLOOR_PCT, WORKDAY_HOURS

# --- Precision helpers ------------------------------------------------------


def _decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 0
    if "." not in text:
        return 0
    return len(text.split(".")[1].rstrip("0"))


def assert_2dp(value: Any, field: str) -> None:
    """PRD §2.6: money, percentages, hour and FTE quantities carry 2 decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert _decimals(value) <= 2, f"{field} must carry at most 2 decimals, got {value!r}"


def assert_4dp(value: Any, field: str) -> None:
    """PRD §2.6: scarcity_index, bench ratios and match_score carry 4 decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert _decimals(value) <= 4, f"{field} must carry at most 4 decimals, got {value!r}"


def assert_integer(value: Any, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer, got {type(value).__name__}: {value!r}"
    )


def assert_iso_date(value: Any, field: str) -> None:
    """PRD §2.5: every _date / _on field is a YYYY-MM-DD calendar date."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be an ISO 8601 YYYY-MM-DD date, got {value!r}"
    )


def assert_iso_instant(value: Any, field: str) -> None:
    """PRD §2.5: instants are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC instant, got {value!r}"
    )


def assert_common_fields(row: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: id, created_at, updated_at and version on every entity that
    declares the common field set."""
    assert is_valid_uuid(row["id"]), f"{entity}.id must be a bare UUID, got {row['id']!r}"
    assert_iso_instant(row["created_at"], f"{entity}.created_at")
    assert_iso_instant(row["updated_at"], f"{entity}.updated_at")
    assert_integer(row["version"], f"{entity}.version")
    assert row["version"] >= 1, f"{entity}.version starts at 1, got {row['version']}"


# --- Envelope helpers -------------------------------------------------------


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """PRD §2.2: meta.api_request_id is prefixed 'req_' and
    meta.api_request_timestamp is an ISO 8601 UTC instant."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_iso_instant(meta["api_request_timestamp"], "meta.api_request_timestamp")


# --- Per-entity shape checkers ---------------------------------------------


def assert_practice_group(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "PracticeGroup")
    assert row["geography_code"] in ("NA", "EMEA", "APAC", "LATAM")
    assert_2dp(row["external_sourcing_cap_pct"], "PracticeGroup.external_sourcing_cap_pct")
    assert isinstance(row["level_targets"], dict)
    assert_integer(row["total_headcount"], "PracticeGroup.total_headcount")
    assert_integer(row["bench_headcount"], "PracticeGroup.bench_headcount")
    assert_integer(row["escalated_l2_count"], "PracticeGroup.escalated_l2_count")
    assert_4dp(row["own_bench_ratio"], "PracticeGroup.own_bench_ratio")
    assert_4dp(row["rollup_bench_ratio"], "PracticeGroup.rollup_bench_ratio")
    assert row["posture"] in ("OPEN", "CONSTRAINED", "FROZEN")


def assert_skill(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Skill")
    assert row["family"] in ("CLOUD", "DATA", "SECURITY", "ERP", "AI")
    assert_4dp(row["scarcity_index"], "Skill.scarcity_index")
    assert isinstance(row["retired"], bool)


def assert_consultant(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Consultant")
    assert row["level"] in (
        "ANALYST",
        "CONSULTANT",
        "SENIOR_CONSULTANT",
        "MANAGER",
        "PRINCIPAL",
    )
    assert_2dp(row["cost_rate_usd_per_hour"], "Consultant.cost_rate_usd_per_hour")
    assert_2dp(
        row["standard_bill_rate_usd_per_hour"],
        "Consultant.standard_bill_rate_usd_per_hour",
    )
    assert_integer(
        row["travel_max_nights_per_week"], "Consultant.travel_max_nights_per_week"
    )
    assert isinstance(row["travel_willing_international"], bool)
    assert isinstance(row["industry_experience"], list)
    assert row["availability_status"] in (
        "ASSIGNED",
        "BENCH",
        "RESKILLING",
        "INTERNAL_PROJECT",
        "SEPARATED",
    )
    assert_2dp(row["allocated_pct"], "Consultant.allocated_pct")


def assert_skill_assertion(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "SkillAssertion")
    assert_integer(row["proficiency_level"], "SkillAssertion.proficiency_level")
    assert 1 <= row["proficiency_level"] <= 5
    assert row["assertion_status"] in ("ACTIVE", "EXPIRED")


def assert_demand(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "DemandOpportunity")
    assert_integer(row["min_proficiency_level"], "DemandOpportunity.min_proficiency_level")
    assert_2dp(row["required_fte"], "DemandOpportunity.required_fte")
    assert_integer(row["win_probability_pct"], "DemandOpportunity.win_probability_pct")
    assert_iso_date(row["start_date"], "DemandOpportunity.start_date")
    assert_iso_date(row["end_date"], "DemandOpportunity.end_date")
    assert_integer(
        row["onsite_nights_per_week"], "DemandOpportunity.onsite_nights_per_week"
    )
    assert isinstance(row["is_international"], bool)
    assert_2dp(
        row["standard_rate_usd_per_hour"], "DemandOpportunity.standard_rate_usd_per_hour"
    )
    assert_2dp(
        row["requested_rate_usd_per_hour"],
        "DemandOpportunity.requested_rate_usd_per_hour",
    )
    assert_2dp(
        row["effective_rate_usd_per_hour"],
        "DemandOpportunity.effective_rate_usd_per_hour",
    )
    assert row["pipeline_status"] in (
        "QUALIFYING",
        "QUALIFIED",
        "CLOSED_WON",
        "CLOSED_LOST",
    )
    assert row["staffing_mode"] in (None, "INTERNAL", "EXTERNAL")
    assert row["staffing_status"] in (
        "UNSTAFFED",
        "INTERNAL_STAFFING",
        "EXTERNAL_SOURCING",
        "PARTIALLY_COVERED",
        "COVERED",
    )
    for field in (
        "covered_internal_fte",
        "covered_external_fte",
        "open_fte",
        "weighted_fte",
        "booked_realization_pct",
        "blended_cost_rate_usd_per_hour",
    ):
        assert_2dp(row[field], f"DemandOpportunity.{field}")
    if row["earned_realization_pct"] is not None:
        assert_2dp(row["earned_realization_pct"], "DemandOpportunity.earned_realization_pct")
    if row["blended_margin_pct"] is not None:
        assert_2dp(row["blended_margin_pct"], "DemandOpportunity.blended_margin_pct")
    assert isinstance(row["margin_breach"], bool)
    assert row["closed_outcome"] in (None, "WON", "LOST")


def assert_assignment(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Assignment")
    assert_2dp(row["allocation_pct"], "Assignment.allocation_pct")
    assert_iso_date(row["start_date"], "Assignment.start_date")
    assert_iso_date(row["end_date"], "Assignment.end_date")
    assert row["end_date"] > row["start_date"], (
        "PRD §2.5: the assignment interval is half-open so end_date must be "
        "strictly later than start_date"
    )
    assert row["category"] in ("BILLABLE", "INVESTMENT")
    assert_2dp(row["bill_rate_usd_per_hour"], "Assignment.bill_rate_usd_per_hour")
    assert_2dp(row["cost_rate_usd_per_hour"], "Assignment.cost_rate_usd_per_hour")
    assert_4dp(row["match_score"], "Assignment.match_score")
    assert row["status"] in ("PROPOSED", "CONFIRMED", "ACTIVE", "RELEASED", "CANCELLED")


def assert_bench_spell(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "BenchSpell")
    assert_iso_date(row["started_on"], "BenchSpell.started_on")
    assert row["state"] in (
        "MONITORING",
        "ESCALATED_L1",
        "ESCALATED_L2",
        "RESKILLING",
        "INTERNAL_PROJECT",
        "SEPARATION_PROPOSED",
        "CLOSED",
        "SEPARATED",
    )
    assert_integer(row["escalation_count"], "BenchSpell.escalation_count")
    assert_integer(row["age_days"], "BenchSpell.age_days")
    assert row["separation_decision"] in (None, "APPROVED", "REJECTED")


def assert_reskilling_program(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "ReskillingProgram")
    assert_integer(
        row["target_proficiency_level"], "ReskillingProgram.target_proficiency_level"
    )
    assert_iso_date(row["cohort_start_on"], "ReskillingProgram.cohort_start_on")
    assert_iso_date(row["cohort_end_on"], "ReskillingProgram.cohort_end_on")
    assert_integer(row["seat_capacity"], "ReskillingProgram.seat_capacity")
    assert_integer(row["seats_taken"], "ReskillingProgram.seats_taken")
    assert_integer(row["cooldown_days"], "ReskillingProgram.cooldown_days")
    assert row["status"] in ("PLANNED", "RUNNING", "COMPLETED")


def assert_firm(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "SubcontractorFirm")
    assert row["geo_code"] in ("NA", "EMEA", "APAC", "LATAM")
    assert_integer(
        row["max_concurrent_placements"], "SubcontractorFirm.max_concurrent_placements"
    )
    assert_2dp(row["markup_pct"], "SubcontractorFirm.markup_pct")
    assert_2dp(
        row["pass_through_rate_usd_per_hour"],
        "SubcontractorFirm.pass_through_rate_usd_per_hour",
    )
    assert row["approval_status"] in ("PENDING", "APPROVED", "SUSPENDED")
    assert_integer(
        row["active_placements_count"], "SubcontractorFirm.active_placements_count"
    )


def assert_placement(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "ExternalPlacement")
    assert_2dp(row["fte"], "ExternalPlacement.fte")
    assert_iso_date(row["start_date"], "ExternalPlacement.start_date")
    assert_iso_date(row["end_date"], "ExternalPlacement.end_date")
    assert row["end_date"] >= row["start_date"], (
        "PRD §2.5: the placement interval is closed so end_date must be on or "
        "after start_date"
    )
    assert_2dp(
        row["pass_through_rate_usd_per_hour"],
        "ExternalPlacement.pass_through_rate_usd_per_hour",
    )
    assert_2dp(row["bill_rate_usd_per_hour"], "ExternalPlacement.bill_rate_usd_per_hour")
    assert row["status"] in ("REQUESTED", "APPROVED", "ACTIVE", "TERMINATED")


def assert_discount_approval(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "DiscountApproval")
    for field in (
        "requested_rate_usd_per_hour",
        "standard_rate_usd_per_hour",
        "discount_pct",
        "provisional_realization_pct",
        "blended_cost_rate_usd_per_hour",
        "projected_margin_pct",
    ):
        assert_2dp(row[field], f"DiscountApproval.{field}")
    assert row["required_tier"] in ("NONE", "L1_PRACTICE_PARTNER", "L2_FINANCE")
    assert isinstance(row["tier_escalated"], bool)
    assert row["status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(row["requested_by_user_id"], str)
    assert_integer(row["revision_count"], "DiscountApproval.revision_count")


def assert_utilization_period(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "UtilizationPeriod")
    assert_iso_date(row["period_start_on"], "UtilizationPeriod.period_start_on")
    assert_iso_date(row["period_end_on"], "UtilizationPeriod.period_end_on")
    assert_2dp(row["holiday_hours"], "UtilizationPeriod.holiday_hours")
    assert_integer(row["period_workdays"], "UtilizationPeriod.period_workdays")
    for field in (
        "capacity_hours",
        "net_available_hours",
        "billable_hours",
        "investment_hours",
        "bench_hours",
        "target_utilization_pct",
        "utilization_pct_target_basis",
        "utilization_pct_of_record",
        "variance_pp",
    ):
        assert_2dp(row[field], f"UtilizationPeriod.{field}")
    if row["utilization_pct_available_basis"] is not None:
        assert_2dp(
            row["utilization_pct_available_basis"],
            "UtilizationPeriod.utilization_pct_available_basis",
        )
    assert isinstance(row["hour_overallocated"], bool)
    assert row["status"] in ("OPEN", "CLOSED")


def assert_hiring_forecast(row: Dict[str, Any]) -> None:
    """PRD §2.4: HiringForecast carries only id and created_at from the common
    field set — it has no updated_at and no version."""
    assert is_valid_uuid(row["id"]), f"HiringForecast.id must be a bare UUID: {row['id']!r}"
    assert_iso_instant(row["created_at"], "HiringForecast.created_at")
    assert "updated_at" not in row, (
        "PRD §2.4: HiringForecast does not carry updated_at"
    )
    assert "version" not in row, "PRD §2.4: HiringForecast does not carry version"
    assert_iso_instant(row["generated_at"], "HiringForecast.generated_at")
    assert row["basis"] in ("WEIGHTED", "COMMITTED")
    for field in (
        "weighted_demand_fte",
        "internal_supply_fte",
        "external_supply_fte",
        "gap_fte",
    ):
        assert_2dp(row[field], f"HiringForecast.{field}")
    assert_integer(row["recommended_hires"], "HiringForecast.recommended_hires")


# --- Domain invariant checkers ---------------------------------------------


def assert_hours_conserved(period: Dict[str, Any]) -> None:
    """PRD §3.9: bench_hours = max(0, net_available_hours - billable_hours -
    investment_hours), so the three classified buckets add back up to
    net_available_hours whenever the period is not overallocated."""
    if period["hour_overallocated"]:
        return
    total = (
        period["billable_hours"] + period["investment_hours"] + period["bench_hours"]
    )
    assert total == pytest.approx(period["net_available_hours"], abs=0.01), (
        "billable + investment + bench must reconstitute net_available_hours: "
        f"{total} != {period['net_available_hours']}"
    )


def assert_capacity_from_workdays(period: Dict[str, Any]) -> None:
    """PRD §3.9: capacity_hours = period_workdays * 8."""
    assert period["capacity_hours"] == pytest.approx(
        period["period_workdays"] * WORKDAY_HOURS, abs=0.01
    )
    assert period["net_available_hours"] == pytest.approx(
        period["capacity_hours"] - period["holiday_hours"], abs=0.01
    )


def assert_fte_coverage_conserved(demand: Dict[str, Any]) -> None:
    """PRD §3.4: open_fte = max(0, required_fte - covered_internal_fte -
    covered_external_fte)."""
    expected = max(
        0.0,
        round(
            demand["required_fte"]
            - demand["covered_internal_fte"]
            - demand["covered_external_fte"],
            2,
        ),
    )
    assert demand["open_fte"] == pytest.approx(expected, abs=0.01), (
        "open_fte must be required_fte less internal and external coverage: "
        f"{demand['open_fte']} != {expected}"
    )


def assert_margin_breach_consistent(demand: Dict[str, Any]) -> None:
    """PRD §3.4: margin_breach is true exactly when blended_margin_pct is
    non-null and below the 20.00% margin floor."""
    margin = demand["blended_margin_pct"]
    expected = margin is not None and margin < MARGIN_FLOOR_PCT
    assert demand["margin_breach"] is expected, (
        f"margin_breach {demand['margin_breach']} disagrees with "
        f"blended_margin_pct {margin}"
    )


def assert_bench_ratio(
    group: Dict[str, Any],
    own_bench_ratio: float,
    rollup_bench_ratio: float,
    posture: str,
) -> None:
    assert group["own_bench_ratio"] == pytest.approx(own_bench_ratio, abs=0.00005)
    assert group["rollup_bench_ratio"] == pytest.approx(rollup_bench_ratio, abs=0.00005)
    assert group["posture"] == posture


def assert_version_is(row: Dict[str, Any], expected: int, entity: str = "row") -> None:
    assert row["version"] == expected, (
        f"{entity}.version expected {expected}, got {row['version']}"
    )


def assert_no_rows(items: list) -> None:
    assert items == [], f"expected no rows, got {len(items)}"


def find_by_id(items: list, row_id: str) -> Optional[Dict[str, Any]]:
    for item in items:
        if item.get("id") == row_id:
            return item
    return None
