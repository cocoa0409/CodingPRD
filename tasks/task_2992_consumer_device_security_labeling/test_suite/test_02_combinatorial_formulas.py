"""Multi-factor derived quantities whose evaluation order is observable.

Three formulas are pinned here: the conformance score's nested floor gate and
three-branch grade ladder, the statutory penalty's per-line rounding order, and
the issuance fee's surcharge band read from the subtotal rather than the total.
"""
from test_helpers import (
    ADMIN_INTAKE_USER_ID,
    DEFAULT_CLOCK,
    assert_grant_statuses,
    assert_money_cents,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    factories,
    fixtures,
    make_admin_headers,
)

INTAKE_ADMIN = make_admin_headers(ADMIN_INTAKE_USER_ID)

ROUTER_CATEGORY = {
    "category_code": "HOME_ROUTER",
    "display_name": "Home Router",
    "min_support_period_days": 1095,
}
ROUTER_PRODUCT = {
    "model_name": "Northwind Router R7",
    "sku": "NW-RTR-R7",
    "retail_units_shipped": 40000,
}


def _assert_area_scores(scores, expected, label):
    assert isinstance(scores, dict), f"{label} must be a mapping, got {scores!r}"
    for area, value in expected.items():
        assert_score(scores.get(area), value, f"{label}.{area}")


def _gated_speaker_claim():
    """A self-attested speaker whose only false declaration is AUTH-2."""
    fixtures.set_clock(DEFAULT_CLOCK)
    return fixtures.submitted_claim(
        required_route="SELF_ATTESTATION", conformance={"AUTH-2": False}
    )


def _fully_declared_speaker_claim():
    """The same world with all five criteria self-declared conformant."""
    fixtures.set_clock(DEFAULT_CLOCK)
    return fixtures.submitted_claim(required_route="SELF_ATTESTATION")


def _repeat_offender_second_case():
    """A subject with one upheld case already, plus a second noticed two-line case."""
    fixtures.set_clock(DEFAULT_CLOCK)
    sponsor = fixtures.enrol_manufacturer()
    first = fixtures.open_case(
        sponsor,
        "ZZ-NO-SUCH-CODE1",
        "UNAUTHORIZED_DISPLAY",
        [factories.violation_line("LST-STORE-A", "IN_STORE", 1)],
        headers=INTAKE_ADMIN,
        reporter_note="Label mark on a device that never entered the program.",
    )
    fixtures.issue_notice(first, notice_reference="NOT-2026-1001")
    first_upheld = fixtures.adjudicate(first, "UPHELD")
    second = fixtures.open_case(
        sponsor,
        "ZZ-NO-SUCH-CODE2",
        "UNAUTHORIZED_DISPLAY",
        [
            factories.violation_line("LST-STORE-B", "IN_STORE", 1),
            factories.violation_line("LST-ONLINE-B", "ONLINE", 1),
        ],
        headers=INTAKE_ADMIN,
        reporter_note="Repeat offence across one store and one online listing.",
    )
    fixtures.issue_notice(second, notice_reference="NOT-2026-1002")
    return sponsor, first_upheld, second


def _fee_grant():
    """A TIER_2 router grant issued from a bench-verified approved assessment."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program(
        "THIRD_PARTY_TEST", category_overrides=dict(ROUTER_CATEGORY)
    )
    sponsor = fixtures.enrol_manufacturer()
    claim = fixtures.submitted_claim(
        program=program,
        sponsor=sponsor,
        required_route="THIRD_PARTY_TEST",
        product_overrides=dict(ROUTER_PRODUCT),
    )
    fixtures.book_engagement(claim, fixtures.register_lab())
    fixtures.file_report(claim, [], report_reference="RPT-R7-0002")
    fixtures.decide_claim(claim, "APPROVED")
    claim.refresh_product()
    return fixtures.issue_grant(claim)


class TestAreaFloorGateAndTieredGrade:
    """One false declaration, four area scores, a floor gate and a letter."""

    def test_a_single_weak_area_caps_the_weighted_sum_at_the_gate_score(self):
        """AUTHENTICATION 36.00 gates the 68.80 weighted sum down to 65.00.

        PRD: "If the smallest area score from step two is strictly less than 60.00, the claim has a weak practice area and its overall score is capped: the overall score becomes whichever is smaller of the weighted sum from step three and 65.00, and `gate_applied` is set to true."
        Design: Difficulty/combinatorial_formula/area_floor_gate_and_tiered_grade_in_conformance_score
        """
        claim = _gated_speaker_claim()

        assessment = claim.assessment
        _assert_area_scores(
            assessment["provisional_area_scores"],
            {
                "AUTHENTICATION": 36.00,
                "SOFTWARE_UPDATE": 60.00,
                "DATA_PROTECTION": 100.00,
                "VULN_DISCLOSURE": 100.00,
            },
            "provisional_area_scores",
        )
        assert_score(assessment["decided_min_area_score"], 36.00, "decided_min_area_score")
        assert assessment["gate_applied"] is True, assessment["gate_applied"]
        assert_score(assessment["provisional_overall_score"], 65.00, "provisional_overall_score")
        assert_score(assessment["decided_overall_score"], 65.00, "decided_overall_score")
        assert assessment["provisional_overall_score"] != 68.80, (
            "the ungated weighted sum must not survive the floor gate"
        )

    def test_the_gated_score_falls_below_the_tier_minimum_and_grades_fail(self):
        """65.00 clears none of the three grade thresholds under a 80.80 minimum.

        PRD: "The `grade` is chosen from the overall score by walking three thresholds in order: an overall score of 90.00 or more earns `A`; failing that, 80.00 or more earns `B`; failing that, a score of at least the tier's own `min_overall_score` earns `C`; and anything below that earns `FAIL`."
        Design: Difficulty/combinatorial_formula/area_floor_gate_and_tiered_grade_in_conformance_score
        """
        claim = _gated_speaker_claim()

        assessment = claim.assessment
        assert_status(assessment, "status", "UNDER_REVIEW")
        assert_status(assessment, "grade", "FAIL")
        assert_score(assessment["decided_overall_score"], 65.00, "decided_overall_score")
        reread = claim.refresh_assessment()
        assert_status(reread, "grade", "FAIL")
        assert_score(reread["decided_overall_score"], 65.00, "decided_overall_score")

    def test_a_weakest_area_landing_exactly_on_the_floor_passes_ungated(self):
        """SOFTWARE_UPDATE at exactly 60.00 leaves the weighted 80.80 untouched.

        PRD: "The comparison is strict, so a claim whose weakest area lands exactly on 60.00 passes ungated."
        Design: Difficulty/combinatorial_formula/area_floor_gate_and_tiered_grade_in_conformance_score
        """
        claim = _fully_declared_speaker_claim()

        assessment = claim.assessment
        _assert_area_scores(
            assessment["provisional_area_scores"],
            {
                "AUTHENTICATION": 76.00,
                "SOFTWARE_UPDATE": 60.00,
                "DATA_PROTECTION": 100.00,
                "VULN_DISCLOSURE": 100.00,
            },
            "provisional_area_scores",
        )
        assert_score(assessment["decided_min_area_score"], 60.00, "decided_min_area_score")
        assert assessment["gate_applied"] is False, assessment["gate_applied"]
        assert_score(assessment["provisional_overall_score"], 80.80, "provisional_overall_score")
        assert_score(assessment["decided_overall_score"], 80.80, "decided_overall_score")
        assert_status(assessment, "grade", "B")


class TestPerLineRoundingOrderInStatutoryPenalty:
    """Two half-cent penalty lines under an aggravation multiplier of 1.25."""

    def test_each_line_is_rounded_before_the_lines_are_summed(self):
        """6037.5 and 7087.5 round to 6038 and 7088, summing to 13126 not 13125.

        PRD: "The rounding order is pinned: round each line's product to whole cents, then add the rounded line amounts together."
        Design: Difficulty/combinatorial_formula/per_line_rounding_order_in_statutory_penalty
        """
        _sponsor, first_upheld, second = _repeat_offender_second_case()
        assert_money_cents(first_upheld["penalty_cents"], 4830, "penalty_cents")

        second_upheld = fixtures.adjudicate(second, "UPHELD")

        assert_status(second_upheld, "penalty_variant", "STATUTORY_SCHEDULE")
        assert_score(second_upheld["aggravation_multiplier"], 1.25, "aggravation_multiplier")
        assert_money_cents(second_upheld["penalty_cents"], 13126, "penalty_cents")
        assert second_upheld["penalty_cents"] != 13125, (
            "summing the unrounded lines and rounding once is the wrong order"
        )

    def test_the_two_rounding_orders_disagree_by_exactly_one_cent(self):
        """The subject's ledger carries 4830 + 13126, and its standing holds at GOOD.

        PRD: "Summing the unrounded line values and rounding once at the end can differ by one or more cents whenever two lines each land exactly on a half cent, so the per-line rounding is part of the contract and not an implementation detail."
        Design: Difficulty/combinatorial_formula/per_line_rounding_order_in_statutory_penalty
        """
        sponsor, _first_upheld, second = _repeat_offender_second_case()

        second_upheld = fixtures.adjudicate(second, "UPHELD")

        assert second_upheld["penalty_cents"] - 13125 == 1, second_upheld["penalty_cents"]
        ledger = sponsor.refresh()
        assert ledger["upheld_case_count"] == 2, ledger["upheld_case_count"]
        assert_penalty_ledger(ledger, outstanding=17956, paid=0, vacated=0)
        assert_money_cents(
            ledger["total_assessed_penalty_cents"], 17956, "total_assessed_penalty_cents"
        )
        assert_status(ledger, "standing", "GOOD")

    def test_the_second_offence_carries_the_pre_increment_aggravation_step(self):
        """One prior upheld case reads as 1.25, not the post-increment 1.50.

        PRD: "A first-time offender therefore carries a multiplier of exactly 1.00, a subject with one prior upheld case carries 1.25, two priors 1.50, three priors 1.75, four priors 2.00, and every subject beyond that stays at the 2.00 cap."
        Design: Difficulty/combinatorial_formula/per_line_rounding_order_in_statutory_penalty
        """
        _sponsor, first_upheld, second = _repeat_offender_second_case()
        assert_score(first_upheld["aggravation_multiplier"], 1.00, "aggravation_multiplier")

        second_upheld = fixtures.adjudicate(second, "UPHELD")

        assert_score(second_upheld["aggravation_multiplier"], 1.25, "aggravation_multiplier")
        assert second_upheld["violation_unit_count"] == 2, second_upheld["violation_unit_count"]


class TestIssuanceFeeBandSelectedFromSubtotal:
    """A 145000-cent subtotal sits in the 10 percent band, not the 18 percent one."""

    def test_the_surcharge_band_is_read_from_the_subtotal(self):
        """The first grant on a TIER_2 router is billed 159500 cents, never 171100.

        PRD: "Re-deriving the band from the finished fee is wrong: a subtotal of 145000 cents sits in the 10 percent band and yields a fee of 159500 cents, whereas that fee of 159500 cents would itself sit in the 18 percent band and yield 171100 cents."
        Design: Difficulty/combinatorial_formula/issuance_fee_band_selected_from_subtotal_not_total
        """
        grant = _fee_grant()

        issued = grant.label_grant
        assert issued["renewal_generation"] == 0, issued["renewal_generation"]
        assert_money_cents(issued["issuance_fee_cents"], 159500, "issuance_fee_cents")
        assert issued["issuance_fee_cents"] != 171100, (
            "the band must not be re-derived from the finished fee"
        )

    def test_the_fee_is_the_subtotal_plus_a_ten_percent_surcharge(self):
        """159500 decomposes as 145000 plus 14500 on a grant that is not yet public.

        PRD: "The surcharge is the subtotal multiplied by that rate, rounded half up to a whole number of cents, and `issuance_fee_cents` is the subtotal plus that surcharge."
        Design: Difficulty/combinatorial_formula/issuance_fee_band_selected_from_subtotal_not_total
        """
        grant = _fee_grant()

        issued = grant.refresh()
        assert_money_cents(issued["issuance_fee_cents"] - 145000, 14500, "surcharge_cents")
        assert_money_cents(issued["issuance_fee_cents"], 159500, "issuance_fee_cents")
        assert_grant_statuses(issued, "PENDING_REGISTRY", "DRAFT")
