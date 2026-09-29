"""Calculations whose two named variants must diverge on the same row.

Covers the preliminary/final mitigation pair on the habitat conservation plan
and the rolling/lifetime pair behind the proponent's compliance standing.
"""

from test_helpers.fixtures import (
    build_scenario,
    read_proponent,
    set_clock,
    setup_two_penalty_reports,
)


class TestMitigationVariantDivergence:
    """PRELIMINARY is coarse and acreage-blind; FINAL is per-row and uplift-aware."""

    def test_preliminary_variant_multiplies_covered_acres_by_the_largest_ratio(self, api):
        """A brand-new plan prices its whole covered acreage at the largest ratio.

        PRD: "The **PRELIMINARY** variant, computed at plan creation and stored in
        `preliminary_mitigation_units`, is deliberately coarse: it takes the single
        **largest** listing ratio anywhere in the candidate set and multiplies the
        plan's whole `covered_acres` by it, rounding half up to two decimal places
        once at the end. It ignores the critical-habitat uplift entirely and it
        ignores each row's own acreage, which is what makes it computable from the
        plan alone."

        The candidate set holds one ENDANGERED row (ratio 3.0) and one THREATENED
        row (ratio 2.0), so the largest ratio is 3.0 and 20.00 covered acres price
        at 60.00 units - a figure no per-row reading of the same two rows produces.

        Design: Difficulty/dual_variant_calc/mitigation_preliminary_vs_final_variant_divergence
        """
        scenario = build_scenario("plan")

        assert scenario["field_determination"]["presence_status"] == "PRESENT"
        assert scenario["query_determination"]["presence_status"] == "PRESUMED_PRESENT"
        assert scenario["plan"]["covered_acres"] == 20.00
        assert scenario["plan"]["preliminary_mitigation_units"] == 60.00

    def test_final_variant_rounds_each_row_then_sums_and_leaves_preliminary_intact(
        self, api
    ):
        """Submission writes the per-row figure without disturbing the coarse one.

        PRD: "The **FINAL** variant, computed at plan submission and stored in
        `final_mitigation_units`, works row by row: for each candidate row it
        multiplies that row's own `habitat_overlap_acres` by that row's own listing
        ratio and by that row's own uplift, **rounds that product half up to two
        decimal places**, and only then sums the rounded per-row figures."

        PRD: "`mitigation_delta_units` is `final_mitigation_units` minus
        `preliminary_mitigation_units`, rounded half up to two decimal places".

        The ENDANGERED row contributes 10.00 x 3.0 x 1.5 = 45.00 and the
        THREATENED row, which names no critical habitat unit, contributes
        7.35 x 2.0 x 1.0 = 14.70, for 59.70 against a preliminary 60.00.

        Design: Difficulty/dual_variant_calc/mitigation_preliminary_vs_final_variant_divergence
        """
        scenario = build_scenario("submitted", funding_cents=0)
        plan = scenario["plan"]

        assert plan["final_mitigation_units"] == 59.70
        assert plan["preliminary_mitigation_units"] == 60.00
        assert plan["mitigation_delta_units"] == -0.30
        assert plan["secured_mitigation_units"] == 59.72
        assert plan["plan_status"] == "SUBMITTED"
        assert plan["funding_status"] == "UNFUNDED"


class TestComplianceStandingVariantDivergence:
    """The same proponent row scores differently at two clock positions."""

    def test_rolling_variant_applies_while_a_report_period_end_sits_in_the_window(
        self, api
    ):
        """A recent reporting period selects the windowed variant.

        PRD: "If **any** of those reports has a `period_end` falling inside the
        closed interval from the window start through *now* - the endpoints count -
        the variant is `ROLLING_12_MONTH`. Otherwise the variant is `LIFETIME`."

        PRD: "An event older than 180 whole days carries **half** its weight; an
        event exactly 180 whole days old carries its **full** weight, because the
        comparison is strictly greater than."

        Read at 2027-06-01 the rejected report is 193 days old and carries 5.5 of
        its weight of 11, while the late-accepted report is 12 days old and carries
        its full weight of 6, so the score is 100 - 11.5.

        Design: Difficulty/dual_variant_calc/compliance_standing_rolling_vs_lifetime_variant_divergence
        """
        scenario = setup_two_penalty_reports()
        set_clock("2027-06-01T00:00:00Z")

        proponent = read_proponent(scenario["proponent"]["id"])

        assert proponent["compliance_variant_applied"] == "ROLLING_12_MONTH"
        assert proponent["compliance_standing_score"] == 88.50

    def test_lifetime_variant_scores_the_same_row_differently_with_no_write_between(
        self, api
    ):
        """Moving the clock forward one year flips the variant and the score.

        PRD: "The consequence is that the same proponent row can return different
        values at two different clock positions with no intervening write of any
        kind."

        Read at 2028-06-01 no report period ends inside the window, so the lifetime
        variant applies and both events are past the decay boundary: the rejected
        report carries 5.5 and the late-accepted report carries 3.0, giving
        100 - 8.5 against the 88.50 the rolling variant returned.

        Design: Difficulty/dual_variant_calc/compliance_standing_rolling_vs_lifetime_variant_divergence
        """
        scenario = setup_two_penalty_reports()
        set_clock("2027-06-01T00:00:00Z")
        rolling = read_proponent(scenario["proponent"]["id"])
        set_clock("2028-06-01T00:00:00Z")

        lifetime = read_proponent(scenario["proponent"]["id"])

        assert lifetime["compliance_variant_applied"] == "LIFETIME"
        assert lifetime["compliance_standing_score"] == 91.50
        assert round(
            lifetime["compliance_standing_score"] - rolling["compliance_standing_score"], 2
        ) == 3.00
        assert lifetime["open_reinitiation_count"] == 0

    def test_report_due_date_and_lateness_are_dated_from_the_logical_clock(self, api):
        """The two penalty-bearing reports differ in lateness, not in shape.

        PRD: "`due_at` is `period_end` advanced by 45 calendar days, and it is a
        date-only value. `is_late` is true when the UTC calendar date of
        `submitted_at` is **strictly later** than `due_at`, so a report filed on the
        due date itself is on time."

        The first report closes 2026-10-31 and is filed at 2026-11-20, well inside
        its 2026-12-15 due date; the second closes 2027-03-31 and is filed at
        2027-05-20, past its due date.

        Design: Difficulty/dual_variant_calc/compliance_standing_rolling_vs_lifetime_variant_divergence
        """
        scenario = setup_two_penalty_reports()

        assert scenario["r1"]["due_at"] == "2026-12-15"
        assert scenario["r1"]["is_late"] is False
        assert scenario["r2"]["is_late"] is True
