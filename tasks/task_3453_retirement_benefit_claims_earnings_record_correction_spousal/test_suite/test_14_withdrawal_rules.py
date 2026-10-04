"""Withdrawal rules: the 12-month window boundary, exact repayment equality, and
the once-per-lifetime bar."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    make_claimant_headers,
    payment_for_month,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestWithdrawalWindowBoundary:
    def test_withdrawal_at_exactly_12_months_succeeds(self, api):
        """PRD §3.6: "No more than twelve months may separate `entitlement_month`
        from the current logical month, else `ERR_WITHDRAWAL_WINDOW_EXPIRED`
        (422)."

        Entitlement 2026-06, clock 2027-06-20: exactly 12 months — the boundary
        is inclusive.

        Design: Difficulty/boundary_precision_check/withdrawal_deadline_exactly_12_months
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        assert entitled["monthly_benefit_cents"] == 8_750
        run_batch_at("2026-06-20T00:00:00Z", "2026-06")

        set_clock("2027-06-20T00:00:00Z")
        withdrawn = validate_success(
            api.withdraw_claim(entitled["id"], 8_750, make_claimant_headers(worker["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdrawal_at_13_months_rejected(self, api):
        """PRD §3.6: "No more than twelve months may separate `entitlement_month`
        from the current logical month, else `ERR_WITHDRAWAL_WINDOW_EXPIRED`
        (422)."

        Entitlement 2026-06, clock 2027-07-01: 13 months — one past the window.

        Design: Difficulty/boundary_precision_check/withdrawal_deadline_exactly_12_months
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        run_batch_at("2026-06-20T00:00:00Z", "2026-06")

        set_clock("2027-07-01T00:00:00Z")
        resp = api.withdraw_claim(entitled["id"], 8_750, make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_WINDOW_EXPIRED, 422)

        unchanged = get_claim(entitled["id"])
        assert unchanged["status"] == "ENTITLED"


class TestRepaymentAndLifetimeBar:
    def test_withdrawal_repayment_shortfall_rejected(self, api):
        """PRD §3.6: "And repayment must be total and simultaneous: the call
        carries `repaid_amount_cents`, which must equal the claim's
        `total_paid_cents` — the sum of `net_paid_cents` over the claim's `PAID`
        and `WITHHELD_FULL` payments — else `ERR_REPAYMENT_SHORTFALL` (422)."

        One payment of 8,750; repaying 8,000 is rejected.

        Design: Corner/validations/withdrawal_repayment_shortfall_rejected
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        run_batch_at("2026-06-20T00:00:00Z", "2026-06")

        set_clock("2026-09-15T00:00:00Z")
        resp = api.withdraw_claim(entitled["id"], 8_000, make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_REPAYMENT_SHORTFALL, 422)

        unchanged = get_claim(entitled["id"])
        assert unchanged["status"] == "ENTITLED"
        payment = payment_for_month(entitled["id"], "2026-06")
        assert payment["status"] == "PAID"

    def test_second_withdrawal_in_lifetime_rejected(self, api):
        """PRD §3.6: "The worker's `withdrawal_used` flag must still be false,
        else `ERR_WITHDRAWAL_ALREADY_USED` (422)."
        PRD §3.6: "The withdrawn claim is treated as never filed: the worker may
        file a fresh claim — the duplicate-active-claim guard does not see
        terminal claims — but may never withdraw again."

        Design: Corner/validations/second_withdrawal_in_lifetime_rejected
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Twice Shy")
        claim_a = file_claim(worker["id"], "RETIREMENT", "2026-06")
        approve_claim(claim_a["id"])
        withdrawn_a = validate_success(
            api.withdraw_claim(claim_a["id"], 0, make_claimant_headers(worker["id"]))
        )
        assert withdrawn_a["status"] == "WITHDRAWN"

        claim_b = file_claim(worker["id"], "RETIREMENT", "2026-06")
        assert claim_b["status"] == "FILED", "WITHDRAWN does not block re-filing"
        approve_claim(claim_b["id"])

        resp = api.withdraw_claim(claim_b["id"], 0, make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ALREADY_USED, 422)

        unchanged = get_claim(claim_b["id"])
        assert unchanged["status"] == "ENTITLED"
