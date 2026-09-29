"""Dual-variant derived quantities on two different entity domains.

The provisional and verified variants of the conformance score read the same
five criterion responses on a `ConformanceAssessment` and disagree; the
statutory and revenue-linked penalty variants read byte-identical case facts on
two `EnforcementCase` rows and disagree.
"""
from test_helpers import (
    ADMIN_INTAKE_USER_ID,
    DEFAULT_CLOCK,
    assert_case_statuses,
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
IDENTICAL_LINE_ITEMS = [
    factories.violation_line("LST-ONLINE-01", "ONLINE", 7),
    factories.violation_line("LST-STORE-01", "IN_STORE", 3),
]


def _assert_area_scores(scores, expected, label):
    assert isinstance(scores, dict), f"{label} must be a mapping, got {scores!r}"
    for area, value in expected.items():
        assert_score(scores.get(area), value, f"{label}.{area}")


def _submitted_router_claim():
    """TIER_2 third-party route; all five criteria self-declared conformant."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program(
        "THIRD_PARTY_TEST", category_overrides=dict(ROUTER_CATEGORY)
    )
    sponsor = fixtures.enrol_manufacturer()
    return fixtures.submitted_claim(
        program=program, sponsor=sponsor, product_overrides=dict(ROUTER_PRODUCT)
    )


def _reported_router_claim():
    """The same claim once a 48-hour bench engagement has reported no failures."""
    claim = _submitted_router_claim()
    fixtures.book_engagement(claim, fixtures.register_lab())
    fixtures.file_report(claim, [], report_reference="RPT-R7-0001")
    return claim


def _two_subject_noticed_cases():
    """One SMALL and one LARGE subject, each noticed on identical line items."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    small = fixtures.enrol_manufacturer()
    large = fixtures.enrol_large_manufacturer()
    grant = fixtures.published_grant(
        fixtures.approved_claim(program=program, sponsor=small)
    )
    case_small = fixtures.open_case(
        small,
        grant.scannable_code,
        "EXPIRED_LABEL_DISPLAY",
        [dict(line) for line in IDENTICAL_LINE_ITEMS],
        headers=INTAKE_ADMIN,
        reporter_note="Label displayed after expiry on 7 online listings and 3 store endcaps.",
    )
    case_large = fixtures.open_case(
        large,
        grant.scannable_code,
        "EXPIRED_LABEL_DISPLAY",
        [dict(line) for line in IDENTICAL_LINE_ITEMS],
        headers=INTAKE_ADMIN,
        reporter_note="Identical line items reported against the large manufacturer.",
    )
    fixtures.issue_notice(case_small, notice_reference="NOT-2026-0001")
    fixtures.issue_notice(case_large, notice_reference="NOT-2026-0002")
    return small, large, case_small, case_large


class TestProvisionalVersusVerifiedConformanceScore:
    """The same five responses under both variants of the scoring pass."""

    def test_verified_variant_pays_full_weight_where_the_provisional_variant_discounted(self):
        """A completed bench report lifts the same responses from 80.80 to 100.00.

        PRD: "In the verified variant the logic inverts for lab-verifiable criteria: when `requires_lab_verification` is true, the criterion earns its full `weight` if `lab_result` is `PASS` and nothing if it is anything else, and `self_declared_conformant` is ignored entirely; when `requires_lab_verification` is false, the criterion earns its full `weight` if `self_declared_conformant` is true and nothing otherwise."
        Design: Difficulty/dual_variant_calc/provisional_vs_verified_conformance_score_on_router_assessment
        """
        claim = _submitted_router_claim()
        submitted = claim.assessment
        assert_score(submitted["provisional_overall_score"], 80.80, "provisional_overall_score")
        _assert_area_scores(
            submitted["provisional_area_scores"],
            {
                "AUTHENTICATION": 76.00,
                "SOFTWARE_UPDATE": 60.00,
                "DATA_PROTECTION": 100.00,
                "VULN_DISCLOSURE": 100.00,
            },
            "provisional_area_scores",
        )

        fixtures.book_engagement(claim, fixtures.register_lab())
        engagement = fixtures.file_report(claim, [], report_reference="RPT-R7-0001")

        assert_status(engagement, "status", "COMPLETED")
        assessment = claim.refresh_assessment()
        assert_score(assessment["verified_overall_score"], 100.00, "verified_overall_score")
        _assert_area_scores(
            assessment["verified_area_scores"],
            {
                "AUTHENTICATION": 100.00,
                "SOFTWARE_UPDATE": 100.00,
                "DATA_PROTECTION": 100.00,
                "VULN_DISCLOSURE": 100.00,
            },
            "verified_area_scores",
        )
        divergence = round(
            float(assessment["verified_overall_score"])
            - float(assessment["provisional_overall_score"]),
            2,
        )
        assert divergence == 19.20, f"the two variants must diverge by 19.20, got {divergence}"

    def test_decided_score_takes_the_verified_variant_on_a_third_party_route(self):
        """The report writes the verified set and hands it to `decided_overall_score`.

        PRD: "It then recomputes the assessment in the verified variant of §3.4, writing `verified_area_scores`, `verified_overall_score`, `decided_min_area_score` and `gate_applied`, and because a tested assessment is by definition on the `THIRD_PARTY_TEST` route it also sets `decided_overall_score` from `verified_overall_score` and re-derives `grade`."
        Design: Difficulty/dual_variant_calc/provisional_vs_verified_conformance_score_on_router_assessment
        """
        claim = _reported_router_claim()
        assessment = claim.refresh_assessment()

        assert_score(assessment["decided_overall_score"], 100.00, "decided_overall_score")
        assert_score(assessment["decided_min_area_score"], 100.00, "decided_min_area_score")
        assert assessment["gate_applied"] is False, "no area sits below the 60.00 floor"
        assert_status(assessment, "grade", "A")

    def test_the_losing_provisional_variant_is_not_substituted_for_the_decided_score(self):
        """The verified pass leaves the provisional set standing beside it.

        PRD: "The result of the deciding variant is written to `decided_overall_score`: it takes the value of `provisional_overall_score` on a `SELF_ATTESTATION` route and the value of `verified_overall_score` on a `THIRD_PARTY_TEST` route, and it is that field which the approval gate compares against `min_overall_score`."
        Design: Difficulty/dual_variant_calc/provisional_vs_verified_conformance_score_on_router_assessment
        """
        claim = _reported_router_claim()
        assessment = claim.refresh_assessment()

        assert_score(assessment["provisional_overall_score"], 80.80, "provisional_overall_score")
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
        assert_score(assessment["decided_overall_score"], 100.00, "decided_overall_score")
        assert float(assessment["decided_overall_score"]) != float(
            assessment["provisional_overall_score"]
        ), "the discounted provisional score must not stand in for the decided score"

    def test_submission_alone_leaves_the_verified_and_decided_scores_null(self):
        """Nothing is corroborated until the bench reports, so both stay null.

        PRD: "What happens next depends on the route: when `route` is `SELF_ATTESTATION` the provisional score *is* the decided score, so `decided_overall_score` is set from `provisional_overall_score` and `grade` is derived from it; when `route` is `THIRD_PARTY_TEST` the assessment deliberately leaves `verified_overall_score`, `decided_overall_score` and `grade` null, because nothing has yet been corroborated."
        Design: Difficulty/dual_variant_calc/provisional_vs_verified_conformance_score_on_router_assessment
        """
        claim = _submitted_router_claim()
        assessment = claim.assessment

        assert_status(assessment, "status", "UNDER_REVIEW")
        assert assessment["verified_overall_score"] is None, assessment["verified_overall_score"]
        assert assessment["verified_area_scores"] is None, assessment["verified_area_scores"]
        assert assessment["decided_overall_score"] is None, assessment["decided_overall_score"]
        assert assessment["grade"] is None, assessment["grade"]
        assert_score(assessment["decided_min_area_score"], 60.00, "decided_min_area_score")
        assert assessment["gate_applied"] is False, "60.00 is not strictly below the floor"


class TestStatutoryVersusRevenueLinkedPenalty:
    """Two cases, identical facts, two penalty variants selected by the subject."""

    def test_identical_line_items_settle_at_different_penalties_by_enterprise_class(self):
        """35476 cents under the schedule against 3920000 cents under revenue.

        PRD: "Two subjects reported for identical line items on an identical `violation_type` will draw different penalties whenever their `enterprise_class` values differ, and neither number is wrong; the variant that applied is recorded in `penalty_variant` so the difference is always auditable."
        Design: Difficulty/dual_variant_calc/statutory_vs_revenue_linked_penalty_on_two_manufacturer_cases
        """
        _small, _large, case_small, case_large = _two_subject_noticed_cases()

        upheld_small = fixtures.adjudicate(case_small, "UPHELD")
        upheld_large = fixtures.adjudicate(case_large, "UPHELD")

        assert_case_statuses(upheld_small, "ADJUDICATED_UPHELD", "ASSESSED")
        assert_case_statuses(upheld_large, "ADJUDICATED_UPHELD", "ASSESSED")
        assert_status(upheld_small, "penalty_variant", "STATUTORY_SCHEDULE")
        assert_status(upheld_large, "penalty_variant", "REVENUE_LINKED")
        assert_score(upheld_small["aggravation_multiplier"], 1.00, "aggravation_multiplier")
        assert_score(upheld_large["aggravation_multiplier"], 1.00, "aggravation_multiplier")
        assert upheld_small["violation_unit_count"] == 10, upheld_small["violation_unit_count"]
        assert upheld_large["violation_unit_count"] == 10, upheld_large["violation_unit_count"]
        assert_money_cents(upheld_small["penalty_cents"], 35476, "penalty_cents")
        assert_money_cents(upheld_large["penalty_cents"], 3920000, "penalty_cents")
        assert upheld_large["penalty_cents"] != upheld_small["penalty_cents"], (
            "the two variants must not collapse onto one number"
        )

    def test_revenue_linked_subject_is_not_charged_the_statutory_line_schedule(self):
        """Each subject's ledger carries only the amount its own variant struck.

        PRD: "For a `LARGE` subject the variant is `REVENUE_LINKED`, and `violation_line_items` is ignored entirely."
        Design: Difficulty/dual_variant_calc/statutory_vs_revenue_linked_penalty_on_two_manufacturer_cases
        """
        small, large, case_small, case_large = _two_subject_noticed_cases()

        fixtures.adjudicate(case_small, "UPHELD")
        fixtures.adjudicate(case_large, "UPHELD")

        small_ledger = small.refresh()
        large_ledger = large.refresh()
        assert_penalty_ledger(small_ledger, outstanding=35476, paid=0, vacated=0)
        assert_penalty_ledger(large_ledger, outstanding=3920000, paid=0, vacated=0)
        assert_money_cents(
            large_ledger["outstanding_penalty_cents"], 3920000, "outstanding_penalty_cents"
        )
        assert large_ledger["outstanding_penalty_cents"] != 35476, (
            "the line-item schedule must not reach a revenue-linked subject"
        )

    def test_both_subject_ledgers_total_exactly_what_was_assessed(self):
        """Every case ever opened against the subject feeds one recomputation.

        PRD: "Then `outstanding_penalty_cents` is the sum of `penalty_cents` over those cases whose `penalty_status` is `ASSESSED`; `paid_penalty_cents` is the sum over those whose `penalty_status` is `PAID`; `vacated_penalty_cents` is the sum over those whose `penalty_status` is `VACATED`; and `total_assessed_penalty_cents` is the sum over those whose `penalty_status` is any of `ASSESSED`, `PAID` or `VACATED`."
        Design: Difficulty/dual_variant_calc/statutory_vs_revenue_linked_penalty_on_two_manufacturer_cases
        """
        small, large, case_small, case_large = _two_subject_noticed_cases()

        fixtures.adjudicate(case_small, "UPHELD")
        fixtures.adjudicate(case_large, "UPHELD")

        small_ledger = small.refresh()
        large_ledger = large.refresh()
        assert_money_cents(
            small_ledger["total_assessed_penalty_cents"], 35476, "total_assessed_penalty_cents"
        )
        assert_money_cents(
            large_ledger["total_assessed_penalty_cents"], 3920000, "total_assessed_penalty_cents"
        )
        assert small_ledger["upheld_case_count"] == 1, small_ledger["upheld_case_count"]
        assert large_ledger["upheld_case_count"] == 1, large_ledger["upheld_case_count"]
