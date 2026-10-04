"""Core benefit computation: AIME aggregation, PIA bend-point tiers, WEP variant
selection, and the indexation window boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker,
    create_worker_with_awi_record,
    earnings_year_row,
    file_claim,
    post_awi_wage_reports,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestBendPointTierSaturation:
    def test_full_career_aime_and_pia(self, api):
        """PRD §3.5: "The **average indexed monthly earnings** select the 35
        highest `indexed_earnings_cents` values across the worker's ledger rows;
        years with no row count as zero and are included in the computation base,
        and when equal values compete for the last selection slot the choice
        among them is immaterial because it cannot change the sum. The sum of the
        selected years is divided by 420 — 35 computation years times 12 months —
        to obtain average monthly earnings, and that monthly average is rounded
        down to the next lower whole dollar and stored in cents as `aime_cents`."
        PRD §3.5: "The PIA is ninety percent of the portion of AIME up to the
        first bend point, plus thirty-two percent of the portion between the two
        bend points, plus fifteen percent of any portion above the second; the
        three exact tier amounts are summed without rounding and the dime floor is
        applied once to the total, yielding `pia_cents`."

        35 years 1989-2023 each at AWI(y) all index to 1,950,000 (AWI of
        eligibility_year-2 = 2024): AIME = 68,250,000/420 floored to the dollar
        = 162,500; PIA = dime_floor(0.90*103,000 + 0.32*59,500) = 111,740.

        Design: Difficulty/combinatorial_formula/bend_point_tier_saturation
        """
        worker = create_worker_with_awi_record(1989, 2023, full_name="Full Career Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["aime_cents"] == 162_500
        # Tier saturation is observable: a flat 0.90 formula would give 146,250.
        assert entitled["pia_cents"] == 111_740
        assert entitled["pia_cents"] != 146_250, "0.90-flat formula is non-conformant"

    def test_full_career_monthly_benefit_at_62(self, api):
        """PRD §3.5: "When the claimant is younger than full retirement age at
        entitlement, the benefit factor is one, reduced by five nine-hundredths
        for each of the first thirty-six early months and by five
        twelve-hundredths for each month beyond thirty-six".
        PRD §3.4: "`reduction_months` (the count of months claimed before full
        retirement age, zero when claiming at or after it)".

        Claiming at 744 months against FRA 804: factor = 1 - 36*5/900 - 24*5/1200
        = 0.70; monthly = dime_floor(111,740 * 0.70) = 78,210.

        Design: Difficulty/combinatorial_formula/bend_point_tier_saturation
        """
        worker = create_worker_with_awi_record(1989, 2023, full_name="Full Career Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["claiming_age_months"] == 744
        assert entitled["reduction_months"] == 60
        assert entitled["monthly_benefit_cents"] == 78_210


class TestWepVariantSelection:
    def test_standard_pia_when_no_pension(self, api):
        """PRD §3.5: "The **windfall elimination provision** substitutes a weaker
        first tier when the worker draws a non-covered pension —
        `noncovered_pension_monthly_cents` above zero — and has fewer than thirty
        years of substantial coverage".

        Without a pension the standard formula applies: three AWI years 2021-2023
        index to 1,950,000 each; AIME = floor(5,850,000/420)*100 = 13,900; PIA =
        dime_floor(0.90*13,900) = 12,510; monthly at 744 months = dime_floor(
        12,510 * 0.70) = 8,750.

        Design: Difficulty/dual_variant_calc/wep_vs_standard_pia_divergence
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Std Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["aime_cents"] == 13_900
        assert entitled["pia_cents"] == 12_510
        assert entitled["monthly_benefit_cents"] == 8_750

    def test_wep_pia_when_pension_present(self, api):
        """PRD §3.5: "The substitute first-tier factor is ninety percent reduced
        by five percentage points for each year of substantial coverage short of
        thirty, never below forty percent — so a worker with twenty or fewer
        substantial years sits at the forty-percent floor, and thirty or more
        years exempts the worker from WEP entirely. The raw windfall-adjusted PIA
        is the same three-tier formula with the substitute first-tier factor,
        dime-floored. The nominal WEP reduction is the standard PIA minus that
        raw figure, but the reduction actually applied is capped by the WEP
        guarantee at one-half the worker's monthly non-covered pension, the half
        rounded down to a whole cent; the final PIA is the standard PIA minus the
        lesser of the nominal reduction and that cap. For identical earnings the
        result is strictly smaller than the standard PIA."

        Identical record plus a 60,000/month pension: YOC = 3 (each AWI year
        clears the substantial threshold), tier-1 factor 0.40, wep_raw =
        dime_floor(0.40*13,900) = 5,560; reduction 6,950 < guarantee cap
        floor(60,000/2) = 30,000, so final PIA = 12,510 - 6,950 = 5,560;
        monthly = dime_floor(5,560 * 0.70) = 3,890.

        Design: Difficulty/dual_variant_calc/wep_vs_standard_pia_divergence
        """
        worker = create_worker_with_awi_record(
            2021, 2023,
            full_name="Wep Worker",
            noncovered_pension_monthly_cents=60_000,
            noncovered_pension_start_month="2025-01",
        )
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["aime_cents"] == 13_900, "identical earnings inputs"
        assert entitled["pia_cents"] == 5_560, "WEP 0.40 tier-1 factor, guarantee not binding"
        assert entitled["monthly_benefit_cents"] == 3_890


class TestEdgeRecords:
    def test_aime_zero_when_no_earnings_record(self, api):
        """PRD §3.5: "years with no row count as zero and are included in the
        computation base".

        With no ledger rows at all, AIME = 0 over the 420-month base; PIA and
        monthly benefit are 0 and the claim still approves to ENTITLED.

        Design: Corner/calculations/aime_zero_when_no_earnings_record
        """
        worker = create_worker(full_name="Zero Record")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        assert entitled["status"] == "ENTITLED"
        assert entitled["aime_cents"] == 0
        assert entitled["pia_cents"] == 0
        assert entitled["monthly_benefit_cents"] == 0

    def test_indexation_face_value_at_eligibility_minus_two(self, api):
        """PRD §3.1: "For every ledger row whose `tax_year` falls before the
        second year prior to the worker's `eligibility_year`, the
        `indexed_earnings_cents` is the row's `posted_earnings_cents` multiplied
        by the average wage index of that second-prior year and divided by the
        average wage index of the `tax_year`, rounded half up to whole cents; rows
        at or after that point enter at face value."

        Eligibility year 2026, second-prior 2024: tax_year 2025 is at/after the
        boundary and enters at face value 1,975,000. AIME =
        floor(1,975,000/42,000)*100 = 4,700; PIA = dime_floor(0.90*4,700) = 4,230;
        monthly = dime_floor(4,230*0.70) = 2,960.

        Design: Corner/calculations/indexation_face_value_at_eligibility_minus_two
        """
        worker = create_worker(full_name="Face Value")
        post_awi_wage_reports(worker["id"], 2025, 2025)
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        entitled = approve_claim(claim["id"])

        row = earnings_year_row(worker["id"], 2025)
        assert row["indexed_earnings_cents"] == 1_975_000, "face value, no indexation factor"
        assert entitled["aime_cents"] == 4_700
        assert entitled["pia_cents"] == 4_230
        assert entitled["monthly_benefit_cents"] == 2_960
