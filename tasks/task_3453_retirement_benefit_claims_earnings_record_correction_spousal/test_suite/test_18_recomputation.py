"""Recomputation cascades: correction approval raising the benefit, the ledger
conservation invariant, and negative deltas opening overpayment cases."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker_with_awi_record,
    file_claim,
    file_correction,
    get_claim,
    list_recomputation_events,
    payment_for_month,
    list_payments,
    run_batch,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_34_year_claim(api):
    """Worker with 34 AWI years 1989-2022 (no 2023 row): AIME 157,800, PIA
    110,230, monthly 77,160 at age 744; three payments for 2026-06..2026-08."""
    worker, entitled = setup_entitled_retirement(
        1989, 2022, "2026-06", approve_clock_iso="2026-06-20T00:00:00Z"
    )
    assert entitled["aime_cents"] == 157_800
    assert entitled["pia_cents"] == 110_230
    assert entitled["monthly_benefit_cents"] == 77_160
    run_batch("2026-06")
    run_batch_at("2026-07-01T00:00:00Z", "2026-07")
    run_batch_at("2026-08-01T00:00:00Z", "2026-08")
    correction = file_correction(worker["id"], 2023, 1_925_000, "TAX_RETURN")
    return worker, entitled, correction


class TestCorrectionApprovalChain:
    def test_correction_approval_recomputes_and_credits(self, api):
        """PRD §3.2: "Second, every claim of that worker in `ENTITLED` or
        `SUSPENDED` status is recomputed — fresh `pia_cents` and
        `monthly_benefit_cents` — and a recomputation event with `trigger`
        `CORRECTION_APPROVED` is appended to each. Third, the retroactive delta
        of §3.5 settles: a positive delta adds to the claim's
        `underpayment_credit_cents`, while a negative delta automatically opens
        an overpayment case for the shortfall."
        PRD §3.5: "The retroactive delta is the change in monthly benefit
        multiplied by the count of the claim's payments in `PAID` or
        `WITHHELD_FULL` status — positive meaning the claimant was underpaid".

        Approving the missing 2023 year (indexed 1,950,000) lifts the record to
        35 AWI-level years: AIME 162,500, PIA 111,740, monthly 78,210; retro
        delta (78,210 - 77,160) * 3 = 3,150.

        Design: Difficulty/transitive_cascade/correction_approval_recomputation_chain
        """
        worker, entitled, correction = _setup_34_year_claim(api)

        validate_success(api.approve_correction(correction["id"], CS))

        events = list_recomputation_events(entitled["id"])
        assert len(events) == 1
        event = events[0]
        assert event["trigger"] == "CORRECTION_APPROVED"
        assert event["old_pia_cents"] == 110_230
        assert event["new_pia_cents"] == 111_740
        assert event["old_monthly_benefit_cents"] == 77_160
        assert event["new_monthly_benefit_cents"] == 78_210
        assert event["retro_delta_cents"] == 3_150
        assert event["resolution"] == "UNDERPAYMENT_CREDIT"

        claim = get_claim(entitled["id"])
        assert claim["underpayment_credit_cents"] == 3_150
        assert claim["pia_cents"] == 111_740
        assert claim["monthly_benefit_cents"] == 78_210

    def test_next_payment_drains_underpayment_credit_in_full(self, api):
        """PRD §3.7: "The claim's outstanding underpayment credit drains in full
        into this payment as its `underpayment_credit_cents`, emptying the
        claim's pool. The `net_paid_cents` is the gross minus the withholding
        plus the credit."

        The 2026-09 payment: gross 78,210 + credit 3,150 = net 81,360; the
        claim's pool returns to 0.

        Design: Difficulty/transitive_cascade/correction_approval_recomputation_chain
        """
        worker, entitled, correction = _setup_34_year_claim(api)
        validate_success(api.approve_correction(correction["id"], CS))

        run_batch_at("2026-09-10T00:00:00Z", "2026-09")

        payment = payment_for_month(entitled["id"], "2026-09")
        assert payment["gross_cents"] == 78_210
        assert payment["underpayment_credit_cents"] == 3_150
        assert payment["net_paid_cents"] == 81_360

        claim = get_claim(entitled["id"])
        assert claim["underpayment_credit_cents"] == 0


class TestLedgerConservation:
    def test_positive_delta_conserves_lifetime_ledger(self, api):
        """PRD §3.5: "The retroactive delta is the change in monthly benefit
        multiplied by the count of the claim's payments in `PAID` or
        `WITHHELD_FULL` status — positive meaning the claimant was underpaid —
        with the pinned simplification that past months are not restated for
        COLA: the current factor applies uniformly to all past payments."

        Two payments at 8,750 plus the 5,800 retro credit equal 2 x 11,650 =
        23,300: the corrected rate owed for each paid month.

        Design: Difficulty/compensating_invariant/recomputation_ledger_conservation_invariant
        """
        worker, entitled = setup_entitled_retirement(
            2020, 2022, "2026-06", approve_clock_iso="2026-06-20T00:00:00Z"
        )
        assert entitled["monthly_benefit_cents"] == 8_750
        run_batch("2026-06")
        run_batch_at("2026-07-01T00:00:00Z", "2026-07")

        correction = file_correction(worker["id"], 2023, 1_925_000, "EMPLOYER_LETTER")
        validate_success(api.approve_correction(correction["id"], CS))

        paid_sum = sum(p["net_paid_cents"] for p in list_payments(entitled["id"]))
        claim = get_claim(entitled["id"])
        assert claim["monthly_benefit_cents"] == 11_650
        assert paid_sum + claim["underpayment_credit_cents"] == 2 * 11_650 == 23_300

        events = list_recomputation_events(entitled["id"])
        assert events[0]["retro_delta_cents"] == 5_800
        assert events[0]["resolution"] == "UNDERPAYMENT_CREDIT"

    def test_credit_drain_keeps_ledger_conserved(self, api):
        """PRD §3.7: "The claim's outstanding underpayment credit drains in full
        into this payment as its `underpayment_credit_cents`, emptying the
        claim's pool. The `net_paid_cents` is the gross minus the withholding
        plus the credit."

        The 2026-08 payment: gross 11,650 + credit 5,800 = net 17,450;
        cumulative net 17,500 + 17,450 = 34,950 = 3 x 11,650.

        Design: Difficulty/compensating_invariant/recomputation_ledger_conservation_invariant
        """
        worker, entitled = setup_entitled_retirement(
            2020, 2022, "2026-06", approve_clock_iso="2026-06-20T00:00:00Z"
        )
        run_batch("2026-06")
        run_batch_at("2026-07-01T00:00:00Z", "2026-07")
        correction = file_correction(worker["id"], 2023, 1_925_000, "EMPLOYER_LETTER")
        validate_success(api.approve_correction(correction["id"], CS))

        run_batch_at("2026-08-01T00:00:00Z", "2026-08")

        payment = payment_for_month(entitled["id"], "2026-08")
        assert payment["gross_cents"] == 11_650
        assert payment["underpayment_credit_cents"] == 5_800
        assert payment["net_paid_cents"] == 17_450

        cumulative = sum(p["net_paid_cents"] for p in list_payments(entitled["id"]))
        assert cumulative == 3 * 11_650 == 34_950


class TestNegativeDelta:
    def test_recomputation_negative_delta_creates_overpayment(self, api):
        """PRD §3.5: "a negative delta automatically opens an overpayment case
        for the absolute amount, spanning the first through the last paid month,
        with `reason` `RECOMPUTATION`, status `NOTIFIED`, and `created_by` set to
        the literal string "system", and the resolution is `OVERPAYMENT_CREATED`;
        a zero delta resolves as `NONE`."

        Correcting 2023 DOWN to 500,000 (indexed 506,494) cuts AIME to 10,400,
        PIA to 9,360, monthly to 6,550; retro delta (6,550 - 8,750) * 2 =
        -4,400 opens a system case of 4,400.

        Design: Corner/calculations/recomputation_negative_delta_creates_overpayment
        """
        worker, entitled = setup_entitled_retirement(
            2021, 2023, "2026-06", approve_clock_iso="2026-06-20T00:00:00Z"
        )
        assert entitled["monthly_benefit_cents"] == 8_750
        run_batch("2026-06")
        run_batch_at("2026-07-01T00:00:00Z", "2026-07")

        correction = file_correction(worker["id"], 2023, 500_000, "EMPLOYER_LETTER")
        validate_success(api.approve_correction(correction["id"], CS))

        events = list_recomputation_events(entitled["id"])
        assert len(events) == 1
        event = events[0]
        assert event["trigger"] == "CORRECTION_APPROVED"
        assert event["new_monthly_benefit_cents"] == 6_550
        assert event["retro_delta_cents"] == -4_400
        assert event["resolution"] == "OVERPAYMENT_CREATED"

        cases = validate_success(api.list_claim_overpayment_cases(entitled["id"], CS))
        assert len(cases) == 1
        case = cases[0]
        assert case["amount_cents"] == 4_400
        assert case["reason"] == "RECOMPUTATION"
        assert case["status"] == "NOTIFIED"
        assert case["created_by"] == "system"

        claim = get_claim(entitled["id"])
        assert claim["monthly_benefit_cents"] == 6_550
