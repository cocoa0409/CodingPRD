"""Difficulty coverage: combinatorial formulas (IEP branch selection, and the
pinned aggregate-then-round order of the Part D penalty)."""

from test_helpers import (
    PART_B,
    PART_D,
    assert_premium_determination,
    create_determination,
    enroll,
    list_penalties,
    publish_rate_schedule,
    register_beneficiary,
    set_clock,
    submit_tax_record,
)


class TestIepCoverageStartFourWayBranch:
    """Attainment month 2026-12 for both enrollees; the enrollment clock month
    alone selects the effective-month branch."""

    def test_iep_enrollment_during_attainment_month(self, client):
        """PRD section 3.2: "For example, with an attainment month of 2026-12,
        enrolling in 2026-12 produces coverage effective 2027-01". PRD
        section 3.2: "Under the IEP, with `T` denoting the attainment month:
        enrolling before `T` yields an effective month of `T` itself;
        enrolling during `T` yields the month after enrollment".

        Design: Difficulty/combinatorial_formula/iep_coverage_start_four_way_branch
        """
        set_clock(client, "2026-12-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1961-12-14", full_name="X Branch"
        )
        enrollment = enroll(client, beneficiary, part=PART_B)
        assert enrollment["enrolled_via_window"] == "IEP"
        assert enrollment["effective_month"] == "2027-01"
        assert enrollment["enrollment_status"] == "PENDING"

    def test_iep_enrollment_two_months_after_attainment(self, client):
        """PRD section 3.2: "enrolling in 2027-02 produces coverage effective
        2027-05." PRD section 3.2: "enrolling two or three months after `T`
        yields three months after the enrollment month."

        Design: Difficulty/combinatorial_formula/iep_coverage_start_four_way_branch
        """
        set_clock(client, "2027-02-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1961-12-14", full_name="Y Branch"
        )
        enrollment = enroll(client, beneficiary, part=PART_B)
        assert enrollment["enrolled_via_window"] == "IEP"
        assert enrollment["effective_month"] == "2027-05"
        assert enrollment["enrollment_status"] == "PENDING"


class TestPartDLepAggregateVsPerMonthRounding:
    """Seven uncovered months against the 3450-cent national base: aggregate
    241.5 rounds half-up to 240; the rejected per-month reading would give
    210."""

    def _setup_part_d_gap7(self, client):
        publish_rate_schedule(client, 2026)
        set_clock(client, "2026-03-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-05-22", full_name="Dee Seven"
        )
        enrollment = enroll(client, beneficiary, part=PART_D)
        assert enrollment["enrolled_via_window"] == "GEP"
        assert enrollment["effective_month"] == "2026-04"
        submit_tax_record(client, beneficiary["id"], 2024, 5000000)
        return beneficiary

    def test_part_d_lep_aggregates_then_rounds_once(self, client):
        """PRD section 3.4: "seven months produce 241.5, which rounds to 240."
        PRD section 3.4: "Two alternative readings are rejected: rounding each
        month's one percent to the dime and then summing (which would yield
        210 for the seven-month case, not 240)".

        Design: Difficulty/combinatorial_formula/part_d_lep_aggregate_vs_per_month_rounding
        """
        beneficiary = self._setup_part_d_gap7(client)
        determination = create_determination(client, beneficiary, 2026, part=PART_D)
        assert determination["lep_cents"] == 240, (
            "round_dime(7 x 1% x 3450) = round_dime(241.5) = 240, not the "
            "per-month reading of 210"
        )

    def test_part_d_lep_flows_into_total_and_assessment(self, client):
        """PRD section 3.5: "`total_premium_cents` is the exact integer sum of
        base, surcharge, and penalty". PRD section 3.4: "A PenaltyAssessment
        row is created directly in `ACTIVE` status at enrollment time, and
        only when the computed penalty is non-zero — for `PART_B`, when
        `penalty_pct` exceeds zero; for `PART_D`, when the uncovered-month
        count exceeds zero."

        Design: Difficulty/combinatorial_formula/part_d_lep_aggregate_vs_per_month_rounding
        """
        beneficiary = self._setup_part_d_gap7(client)
        penalties = list_penalties(client, beneficiary)
        assert len(penalties) == 1
        assert penalties[0]["gap_months"] == 7
        assert penalties[0]["status"] == "ACTIVE"

        determination = create_determination(client, beneficiary, 2026, part=PART_D)
        assert_premium_determination(determination)
        assert determination["base_premium_cents"] == 3450
        assert determination["irmaa_surcharge_cents"] == 0
        assert determination["lep_cents"] == 240
        assert determination["total_premium_cents"] == 3690
