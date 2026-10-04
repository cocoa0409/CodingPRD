"""Difficulty coverage: boundary precision — the IRMAA lower-bound-inclusive
floor and the eleven/twelve-month Part B penalty threshold."""

from test_helpers import (
    assert_penalty_assessment,
    enroll,
    list_penalties,
    register_beneficiary,
    set_clock,
    setup_final_determination,
)


class TestIrmaaFloorInclusiveBoundary:
    """A MAGI equal to the tier-1 SINGLE floor lands IN tier 1; one cent below
    stays in tier 0."""

    def test_magi_at_tier_floor_lands_in_tier(self, client):
        """PRD section 3.5: "Bracket matching is lower-bound inclusive: MAGI
        exactly equal to a tier's floor lands IN that tier. With a `SINGLE`
        tier-1 floor of 10000000 cents, a MAGI of 10000000 yields tier 1 while
        9999999 yields tier 0."

        Design: Difficulty/boundary_precision_check/irmaa_floor_inclusive_boundary
        """
        _beneficiary, _enrollment, determination = setup_final_determination(
            client, coverage_year=2027, tax_year=2025, magi_cents=10000000
        )
        assert determination["status"] == "FINAL"
        assert determination["tax_year_used"] == 2025
        assert determination["irmaa_tier"] == 1
        assert determination["irmaa_surcharge_cents"] == 7600
        assert determination["base_premium_cents"] == 19000
        assert determination["lep_cents"] == 0
        assert determination["total_premium_cents"] == 26600

    def test_magi_one_cent_below_tier_floor_stays_tier_zero(self, client):
        """PRD section 3.5: "With a `SINGLE` tier-1 floor of 10000000 cents, a
        MAGI of 10000000 yields tier 1 while 9999999 yields tier 0."

        Design: Difficulty/boundary_precision_check/irmaa_floor_inclusive_boundary
        """
        _beneficiary, _enrollment, determination = setup_final_determination(
            client, coverage_year=2027, tax_year=2025, magi_cents=9999999
        )
        assert determination["status"] == "FINAL"
        assert determination["irmaa_tier"] == 0
        assert determination["irmaa_surcharge_cents"] == 0
        assert determination["total_premium_cents"] == 19000


class TestPartBLepGapTwelveVsElevenMonths:
    """floor(gap/12): twelve uncovered months carry a 10 percent lifetime
    penalty; eleven carry none at all."""

    def test_twelve_month_gap_creates_ten_percent_penalty(self, client):
        """PRD section 3.4: "An eleven-month gap therefore carries no penalty
        at all, while a twelve-month gap carries exactly ten percent." PRD
        section 3.4: "A PenaltyAssessment row is created directly in `ACTIVE`
        status at enrollment time, and only when the computed penalty is
        non-zero".

        Design: Difficulty/boundary_precision_check/part_b_lep_gap_12_vs_11_months
        """
        set_clock(client, "2027-02-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-11-15", full_name="X Twelve"
        )
        enrollment = enroll(client, beneficiary, part="PART_B")
        assert enrollment["enrolled_via_window"] == "GEP"
        assert enrollment["effective_month"] == "2027-03"

        # Gap span [2026-03 .. 2027-02] = 12 months -> one full period.
        penalties = list_penalties(client, beneficiary)
        assert len(penalties) == 1
        penalty = penalties[0]
        assert_penalty_assessment(penalty)
        assert penalty["part"] == "PART_B"
        assert penalty["gap_months"] == 12
        assert penalty["full_12month_periods"] == 1
        assert penalty["penalty_pct"] == 10
        assert penalty["status"] == "ACTIVE"

    def test_eleven_month_gap_creates_no_penalty(self, client):
        """PRD section 3.4: "An eleven-month gap therefore carries no penalty
        at all, while a twelve-month gap carries exactly ten percent." PRD
        section 3.4: "A PenaltyAssessment row is created directly in `ACTIVE`
        status at enrollment time, and only when the computed penalty is
        non-zero".

        Design: Difficulty/boundary_precision_check/part_b_lep_gap_12_vs_11_months
        """
        set_clock(client, "2027-01-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-11-15", full_name="Y Eleven"
        )
        enrollment = enroll(client, beneficiary, part="PART_B")
        assert enrollment["enrolled_via_window"] == "GEP"
        assert enrollment["effective_month"] == "2027-02"

        # Gap span [2026-03 .. 2027-01] = 11 months -> floor(11/12) == 0.
        assert list_penalties(client, beneficiary) == []
