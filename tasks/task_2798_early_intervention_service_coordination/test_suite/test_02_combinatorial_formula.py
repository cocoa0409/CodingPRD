"""
Multi-term formulas where the order of operations decides the answer: additive
caseload complexity terms closed by a terminal clamp, and a sliding-scale fee
that rounds each service line before it sums them.
"""

import pytest

from test_helpers import (
    MAX_CASE_WEIGHT_POINTS,
    add_service_line,
    assert_case_weight,
    assert_caseload_summary,
    assert_cents,
    assert_fpl_percent,
    build_plan_with_line,
    create_cost_share,
    read_caseload_summary,
    read_coordinator,
    read_cost_share,
    read_ifsp,
    read_referral,
    record_consent,
)

# A bilingual case in CNT_B for a child whose third birthday is 144 days out.
COMPLEX_CASE = {
    "clock": "2026-05-01T09:00:00Z",
    "coordinator": {
        "full_name": "Beatriz Alvarez",
        "county_code": "CNT_B",
        "language_codes": ["EN", "ES"],
        "max_weighted_caseload_points": 12.00,
    },
    "child": {
        "first_name": "Mateo",
        "last_name": "Ibarra",
        "date_of_birth": "2023-10-01",
        "county_code": "CNT_B",
        "primary_language": "ES",
    },
    "referral": {
        "primary_referral_source": "HOSPITAL",
        "referral_received_date": "2026-05-01",
        "county_code": "CNT_B",
        "presenting_concern": (
            "Global developmental delay following a prolonged NICU stay"
        ),
        "interpreter_required": True,
    },
    "evaluation": {"scheduled_date": "2026-05-04"},
    "family_assessment": {"scheduled_date": "2026-05-06"},
    "completion_clock": "2026-05-10T09:00:00Z",
    "evaluation_completion": {"completion_date": "2026-05-05"},
    "family_completion": {"completion_date": "2026-05-07"},
    "determination": {"determination_date": "2026-05-08"},
    "entry_outcomes": {
        "measurement_date": "2026-05-09",
        "rating_social": 2,
        "rating_knowledge": 2,
        "rating_needs": 3,
    },
    "ifsp": {"meeting_date": "2026-05-09"},
}


def _build_three_line_complex_case(api):
    """The interpreter-and-transition-window case carrying three live lines,
    one line short of the fourth complexity term."""
    case = build_plan_with_line(api, **COMPLEX_CASE)
    for service_type, frequency, units, rate, planned in (
        ("PHYSICAL_THERAPY", 2, 2, 7000, 48),
        ("OCCUPATIONAL_THERAPY", 2, 2, 7000, 48),
    ):
        line_id = add_service_line(
            api,
            case.ifsp_id,
            service_type=service_type,
            frequency_per_month=frequency,
            units_per_session=units,
            unit_rate_cents=rate,
            planned_units_total=planned,
        )
        case.line_ids.append(line_id)
    return case


def _add_fourth_line(api, case):
    line_id = add_service_line(
        api,
        case.ifsp_id,
        service_type="DEVELOPMENTAL_INSTRUCTION",
        frequency_per_month=4,
        units_per_session=1,
        unit_rate_cents=5200,
        planned_units_total=48,
    )
    case.line_ids.append(line_id)
    return line_id


class TestCaseWeightAdditiveTermsAndClamp:
    """Three complexity terms stack onto the pre-plan base and then clamp."""

    def test_fourth_line_pushes_the_summed_terms_into_the_clamp(self, api):
        """
        Base 1.50 plus interpreter 0.50 plus transition window 0.75 plus the
        fourth-line term 0.50 sums to 3.25 and is only then reduced to 3.00.

        PRD 3.2: "Finally, and only after the additions have all been summed,
        the total is clamped into the range from 1.00 to 3.00 points inclusive:
        a total below 1.00 is raised to 1.00, a total above 3.00 is lowered to
        3.00, and the clamp is never applied to an intermediate value."

        Design: Difficulty/combinatorial_formula/caseload_weight_nonlinear_clamp
        """
        case = _build_three_line_complex_case(api)

        # Three live lines: the fourth-line term is not yet earned.
        assert_case_weight(
            read_referral(api, case.referral_id)["case_weight_points"], 2.75
        )

        _add_fourth_line(api, case)

        plan = read_ifsp(api, case.ifsp_id)
        assert plan["service_line_count"] == 4
        assert plan["status"] == "PENDING_CONSENT"

        referral = read_referral(api, case.referral_id)
        assert_case_weight(referral["case_weight_points"], MAX_CASE_WEIGHT_POINTS)

        coordinator = read_coordinator(api, case.coordinator_id)
        assert_case_weight(coordinator["weighted_caseload_points"], 3.00)
        assert coordinator["active_case_count"] == 1
        assert float(coordinator["utilization_ratio"]) == pytest.approx(
            0.2500, abs=0.00005
        )

    def test_caseload_read_grades_the_clamped_total(self, api):
        """
        The computed caseload read reports posture and headroom from the
        clamped weighted total, not from the unclamped sum.

        PRD 3.2: "The posture is `OVER` when weighted points exceed the
        ceiling, `AT_CAP` when they equal it exactly, `NEAR_CAP` when neither of
        those holds but the utilization ratio is at least 0.9000, and `OPEN`
        otherwise — the tests are applied in that order, so an over-cap
        coordinator never reports `NEAR_CAP`."

        Design: Difficulty/combinatorial_formula/caseload_weight_nonlinear_clamp
        """
        case = _build_three_line_complex_case(api)
        _add_fourth_line(api, case)

        summary = read_caseload_summary(api, case.coordinator_id)

        assert_caseload_summary(
            summary,
            coordinator_id=case.coordinator_id,
            active_case_count=1,
            weighted_caseload_points=3.00,
            max_weighted_caseload_points=12.00,
            utilization_ratio=0.2500,
            caseload_posture="OPEN",
            headroom_points=9.00,
        )


# Two lines whose per-line rounding disagrees with a sum-then-round by one cent.
ODD_RATE_LINE_ONE = {
    "service_type": "SPEECH_THERAPY",
    "setting_code": "HOME",
    "frequency_per_month": 3,
    "units_per_session": 1,
    "unit_rate_cents": 4115,
    "planned_units_total": 36,
}
ODD_RATE_LINE_TWO = {
    "service_type": "PHYSICAL_THERAPY",
    "setting_code": "HOME",
    "frequency_per_month": 1,
    "units_per_session": 1,
    "unit_rate_cents": 6789,
    "planned_units_total": 12,
}


def _build_odd_rate_case(api):
    """A consented case whose plan carries the two awkwardly priced lines, in
    the order the fee computation must take them."""
    case = build_plan_with_line(api, line=dict(ODD_RATE_LINE_ONE))
    case.line_ids.append(add_service_line(api, case.ifsp_id, **ODD_RATE_LINE_TWO))
    record_consent(api, case.ifsp_id, case.child_id)
    return case


def _determine(api, case):
    case.cost_share_id = create_cost_share(
        api,
        case.referral_id,
        household_size=3,
        declared_annual_gross_income_cents=9_000_000,
        insurance_use_consent=False,
    )
    return read_cost_share(api, case.cost_share_id)


class TestFeeRoundsEachLineBeforeSumming:
    """The one-cent divergence that pins the order of the fee computation."""

    def test_line_amounts_are_rounded_then_added(self, api):
        """
        617 cents from the 4115-cent line plus 339 from the 6789-cent line is
        956, where a sum-then-round would produce 957.

        PRD 2.9: "in the sliding-scale fee computation, **each eligible service
        line is rounded to whole cents before the lines are summed**, never
        after."

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_before_sum
        """
        case = _build_odd_rate_case(api)

        determination = _determine(api, case)

        assert_cents(
            determination["assessed_monthly_fee_cents"],
            956,
            "assessed_monthly_fee_cents",
        )
        assert determination["assessed_monthly_fee_cents"] != 957

    def test_tier_selection_precedes_the_rounded_summation(self, api):
        """
        The threshold and the tier are settled from the declared income first,
        and it is that tier's rate the per-line amounts are computed with.

        PRD 3.8: "The tier is then selected by `fpl_percent` using
        **inclusive** upper bounds, taking the first tier whose ceiling the
        percentage does not exceed."

        Design: Difficulty/combinatorial_formula/cost_share_per_line_rounding_before_sum
        """
        case = _build_odd_rate_case(api)

        determination = _determine(api, case)

        assert determination["status"] == "PROVISIONAL"
        assert_cents(
            determination["fpl_threshold_cents"], 2_690_000, "fpl_threshold_cents"
        )
        assert_fpl_percent(determination["fpl_percent"], 334.6)
        assert determination["tier_code"] == "TIER_1"
        assert float(determination["coinsurance_rate"]) == pytest.approx(
            0.05, abs=0.001
        )
        assert float(determination["effective_coinsurance_rate"]) == pytest.approx(
            0.05, abs=0.001
        )
        assert_cents(determination["monthly_cap_cents"], 12_000, "monthly_cap_cents")
        assert_cents(
            determination["insurance_offset_cents"], 0, "insurance_offset_cents"
        )
        assert determination["final_monthly_fee_cents"] is None
