"""Two commission projections coexist: the forward-looking book projection and the
chronological as-earned figure. Conflating them is the most expensive mistake.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, assert_cost_precision,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    setup_submitted_enrollment, setup_effectuated_enrollment,
    setup_acknowledged_enrollment,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _is_close(a, b, tol=0.01):
    return abs(a - b) <= tol


class TestBookVersusEarnedCommission:
    """A single EFFECTUATED enrollment carries two provably different money figures."""

    def test_effectuation_pins_both_commission_figures_on_one_enrollment(self):
        """PRD §3.6: "`provisional_commission_cents` is computed by the forward-looking
        projection for this single enrollment, and `final_commission_cents` is the
        enrollment's contribution to the chronological pass."

        Design: Difficulty/dual_variant_calc/dual_variant_book_vs_earned_commission_on_enrollment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)
        enrollment = scn["enrollment"]

        assert enrollment["submission_status"] == "EFFECTUATED"
        assert enrollment["disenrollment_status"] == "ENROLLED"
        assert_cost_precision(enrollment["provisional_commission_cents"])
        assert_cost_precision(enrollment["final_commission_cents"])
        assert enrollment["provisional_commission_cents"] != enrollment["final_commission_cents"], (
            "the forward-looking projection and the chronological as-earned figure are "
            "separate computations and must not collapse to one value"
        )

    def test_as_earned_term_is_one_billed_month_at_the_initial_rate(self):
        """PRD §3.5: "An enrollment whose `disenrollment_status` is not `ENROLLED` is
        billed exactly 1 month, and an enrollment still `ENROLLED` is billed the greater
        of 1 and the whole number of months from its `effective_date` to that cutoff."
        PRD §3.5: "the single enrollment's own contribution to the pass is reported as its
        `final_commission_cents`, and it is 0 for any enrollment that is not `EFFECTUATED`."

        Design: Difficulty/dual_variant_calc/dual_variant_book_vs_earned_commission_on_enrollment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        # Effective date 2026-11-01 is entirely in the future of the clock at
        # 2026-10-01, so the whole-month count floors at 1 and bills the initial rate.
        setup_effectuated_enrollment(scn)
        enrollment = scn["enrollment"]

        assert enrollment["effective_date"] == utc("2026-11-01T00:00:00Z")
        # 1500 cents premium x 1 billed month x 0.20 initial rate
        assert enrollment["final_commission_cents"] == pytest.approx(300.00, abs=0.01), (
            "the chronological pass bills this row a single month at the initial rate"
        )

    def test_not_yet_effectuated_enrollment_contributes_nothing_chronological(self):
        """PRD §3.5: "Enrollments whose `submission_status` is not `EFFECTUATED` are
        skipped entirely."

        Design: Difficulty/dual_variant_calc/dual_variant_book_vs_earned_commission_on_enrollment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_submitted_enrollment(scn)
        enrollment = scn["enrollment"]

        assert enrollment["submission_status"] == "SUBMITTED"
        assert enrollment["final_commission_cents"] == pytest.approx(0.00, abs=0.01)

    def test_book_of_business_reports_the_forward_window(self):
        """PRD §3.5: "The projection window starts at the logical clock and runs forward
        365 days. An enrollment qualifies when its agency matches, its `submission_status`
        is `SUBMITTED`, `ACKNOWLEDGED` or `EFFECTUATED`, and its `effective_date` falls at
        or after the window start and strictly before the window end."

        Design: Difficulty/dual_variant_calc/dual_variant_book_vs_earned_commission_on_enrollment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_submitted_enrollment(scn)

        bob = get_success_data(
            api_client.book_of_business(scn["agency"]["id"], DIRECTOR,
                                        params={"window_days": 365}))
        assert bob["agency_id"] == scn["agency"]["id"]
        assert bob["window_start"] == utc("2026-10-01T00:00:00Z")
        assert bob["window_end"] == utc("2027-10-01T00:00:00Z")
        assert bob["qualifying_enrollment_count"] == 1
        assert_cost_precision(bob["provisional_book_commission_cents"])

    def test_narrow_window_excludes_the_election_entirely(self):
        """PRD §3.5: "The projection window starts at the logical clock and runs forward
        365 days."

        Design: Difficulty/dual_variant_calc/dual_variant_book_vs_earned_commission_on_enrollment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_submitted_enrollment(scn)

        bob = get_success_data(
            api_client.book_of_business(scn["agency"]["id"], DIRECTOR,
                                        params={"window_days": 30}))
        assert bob["qualifying_enrollment_count"] == 0
        assert bob["provisional_book_commission_cents"] == pytest.approx(0.00, abs=0.01)


class TestReserveVersusDisbursement:
    """At acknowledgment one row carries three distinct money figures at once."""

    def test_acknowledgment_posts_a_provisional_renewal_beside_the_initial_entry(self):
        """PRD §3.6: "On success the submission advances to `ACKNOWLEDGED`,
        `acknowledged_on` takes the logical clock, a `RENEWAL` ledger entry is posted in
        status `PROVISIONAL`, and the agency's `commission_balance_cents` is recomputed."
        PRD §3.8: "An `INITIAL` entry takes the annual initial commission as its
        `amount_cents`, unmodified. A `RENEWAL` entry takes the annual renewal commission
        as its `amount_cents`."

        Design: Difficulty/dual_variant_calc/dual_variant_reserve_vs_disbursement_on_acknowledgment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_acknowledged_enrollment(scn)

        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": scn["enrollment"]["id"]}))
        assert len(rows) == 2, "one INITIAL entry at creation and one RENEWAL at acknowledgment"
        assert all(r["status"] == "PROVISIONAL" for r in rows)

        by_type = {r["entry_type"]: r for r in rows}
        # 1500 x 12 x 0.20 = 3600; 1500 x 12 x 0.10 = 1800
        assert by_type["INITIAL"]["amount_cents"] == pytest.approx(3600.00, abs=0.01)
        assert by_type["RENEWAL"]["amount_cents"] == pytest.approx(1800.00, abs=0.01)

        agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
        assert agency["commission_balance_cents"] == pytest.approx(5400.00, abs=0.01), (
            "the conserved balance is the sum over PROVISIONAL and FINALIZED entries"
        )

    def test_forward_looking_attribution_is_not_the_settlement_figure(self):
        """PRD §3.5: "a single enrollment's own share of that projection is reported as
        its `provisional_commission_cents`, computed from the same two rounded terms
        without the agency-wide grouping."
        PRD §3.5: "it is 0 for any enrollment that is not `EFFECTUATED`."

        Design: Difficulty/dual_variant_calc/dual_variant_reserve_vs_disbursement_on_acknowledgment
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_acknowledged_enrollment(scn)
        enrollment = scn["enrollment"]

        provisional = enrollment["provisional_commission_cents"]
        assert not _is_close(provisional, 3600.00), "not the INITIAL settlement amount"
        assert not _is_close(provisional, 1800.00), "not the RENEWAL settlement amount"
        assert not _is_close(provisional, 5400.00), "not the two settlement amounts summed"
        assert enrollment["final_commission_cents"] == pytest.approx(0.00, abs=0.01)