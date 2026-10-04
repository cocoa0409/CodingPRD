"""Difficulty coverage: dual-variant calculations (provisional/final premium,
aggregate rounding of the Part D penalty)."""

from test_helpers import (
    PART_D,
    assert_premium_determination,
    create_determination,
    enroll,
    list_penalties,
    publish_rate_schedule,
    read_determination,
    register_beneficiary,
    set_clock,
    setup_provisional_determination,
    submit_tax_record,
)


class TestPremiumProvisionalVsFinalIrmaaBasis:
    """Same beneficiary, same coverage year: the PROVISIONAL variant prices on
    the tax year three years back (2024, tier 0) and the FINAL variant on the
    tax year two years back (2025, tier 2)."""

    def _setup_provisional_2027(self, client):
        beneficiary, _enrollment, determination = (
            setup_provisional_determination(
                client, coverage_year=2027, tax_year=2024, magi_cents=9000000
            )
        )
        return beneficiary, determination

    def test_provisional_variant_prices_on_older_tax_year(self, client):
        """PRD section 3.5: "When a TaxReturnRecord exists for the tax year
        two years before the coverage year, the determination is created
        directly `FINAL` on that basis; when that record is missing, it is
        created `PROVISIONAL` with the basis falling back to the tax year
        three years before the coverage year."

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_irmaa_basis
        """
        _beneficiary, determination = self._setup_provisional_2027(client)
        assert_premium_determination(determination)
        assert determination["status"] == "PROVISIONAL"
        assert determination["tax_year_used"] == 2024
        assert determination["irmaa_tier"] == 0
        assert determination["base_premium_cents"] == 19000
        assert determination["irmaa_surcharge_cents"] == 0
        assert determination["lep_cents"] == 0
        assert determination["total_premium_cents"] == 19000

    def test_final_variant_repriced_when_newer_tax_year_arrives(self, client):
        """PRD section 3.5: "any `PROVISIONAL` PremiumDetermination whose
        coverage year is exactly two years after the submitted `tax_year`
        finalizes in place — the row flips from `PROVISIONAL` to `FINAL`, its
        `tax_year_used` is set to that year, and its `irmaa_tier`,
        `irmaa_surcharge_cents`, and `total_premium_cents` are recomputed,
        while `lep_cents` is left unchanged." PRD section 3.5: "the same
        beneficiary and coverage year can produce a different total under the
        two bases when the two tax years' MAGI place different tiers."

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_irmaa_basis
        """
        beneficiary, determination = self._setup_provisional_2027(client)
        provisional_total = determination["total_premium_cents"]

        submit_tax_record(client, beneficiary["id"], 2025, 15000000)

        finalized = read_determination(client, determination["id"])
        assert finalized["id"] == determination["id"], "finalized in place"
        assert finalized["status"] == "FINAL"
        assert finalized["tax_year_used"] == 2025
        assert finalized["irmaa_tier"] == 2
        assert finalized["irmaa_surcharge_cents"] == 19000
        assert finalized["lep_cents"] == 0
        assert finalized["total_premium_cents"] == 38000
        assert provisional_total == 19000
        assert finalized["total_premium_cents"] != provisional_total


class TestPartDLepAggregateRoundingHalfUp:
    """Thirteen uncovered months against the 3450-cent national base: the
    pinned reading rounds the aggregate 448.5 half-up to the dime (450), not
    the truncated 440."""

    def _setup_part_d_gap13(self, client):
        publish_rate_schedule(client, 2026)
        set_clock(client, "2026-03-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1959-11-20", full_name="Dee Ellep"
        )
        enrollment = enroll(client, beneficiary, part=PART_D)
        assert enrollment["enrolled_via_window"] == "GEP"
        assert enrollment["effective_month"] == "2026-04"
        submit_tax_record(client, beneficiary["id"], 2024, 5000000)
        return beneficiary

    def test_part_d_penalty_assessment_records_thirteen_gap_months(self, client):
        """PRD section 3.4: "The measured **span** runs from the month after
        `iep_end_month` through the month before the new enrollment's
        `effective_month`, inclusive of both." PRD section 3.4: "the
        `full_12month_periods` and `penalty_pct` fields are populated for
        `PART_B` and are null for `PART_D`, whose basis lives entirely in
        `gap_months`." PRD section 3.4: "A PenaltyAssessment row is created
        directly in `ACTIVE` status at enrollment time, and only when the
        computed penalty is non-zero".

        Design: Difficulty/dual_variant_calc/part_d_lep_aggregate_rounding_half_up
        """
        beneficiary = self._setup_part_d_gap13(client)
        penalties = list_penalties(client, beneficiary)
        assert len(penalties) == 1
        penalty = penalties[0]
        assert penalty["part"] == "PART_D"
        assert penalty["gap_months"] == 13
        assert penalty["full_12month_periods"] is None
        assert penalty["penalty_pct"] is None
        assert penalty["status"] == "ACTIVE"

    def test_part_d_lep_rounded_half_up_to_dime_on_aggregate(self, client):
        """PRD section 3.4: "Thirteen uncovered months against a national base
        of 3450 cents produce 448.5 cents before rounding, which rounds to
        450". PRD section 3.4: "Aggregation order is pinned: the
        multiplication is performed on the aggregate first and rounding
        happens exactly once at the end, to the nearest ten cents half-up."

        Design: Difficulty/dual_variant_calc/part_d_lep_aggregate_rounding_half_up
        """
        beneficiary = self._setup_part_d_gap13(client)
        determination = create_determination(client, beneficiary, 2026, part=PART_D)
        assert_premium_determination(determination)
        assert determination["status"] == "FINAL"
        assert determination["base_premium_cents"] == 3450
        assert determination["irmaa_surcharge_cents"] == 0
        assert determination["lep_cents"] == 450, (
            "round_dime(13 x 1% x 3450) = round_dime(448.5) = 450 half-up, "
            "not the truncated 440"
        )
        assert determination["total_premium_cents"] == 3900
