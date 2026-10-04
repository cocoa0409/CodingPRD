"""Withdrawal invariants: zero net cash after full repayment, re-filing after
withdrawal, and the state-versus-temporal rejection order."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    get_worker,
    list_payments,
    make_claimant_headers,
    make_claims_specialist_headers,
    run_batch,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_two_payment_claim(api):
    """Worker with five AWI years (monthly 14,610 at 62), RETIREMENT entitled
    2026-06, and payments for 2026-06 and 2026-07 (total_paid 29,220)."""
    worker, entitled = setup_entitled_retirement(
        2019, 2023, "2026-06", approve_clock_iso="2026-06-20T00:00:00Z"
    )
    assert entitled["monthly_benefit_cents"] == 14_610
    run_batch("2026-06")
    run_batch_at("2026-07-01T00:00:00Z", "2026-07")
    return worker, entitled


class TestFullRepaymentInvariant:
    def test_withdrawal_repayments_zero_out_lifetime_net_cash(self, api):
        """PRD §3.6: "On success, every payment of the claim in `PAID` or
        `WITHHELD_FULL` status moves to `REPAYED`; the payments remain queryable,
        and the totals reconcile as the claim's `total_paid_cents` returns to
        zero. The worker's `withdrawal_used` becomes true and the claim's
        `monthly_benefit_cents` becomes zero."

        Net disbursed 29,220 minus repaid 29,220 == 0; both payments REPAYED.

        Design: Difficulty/compensating_invariant/withdrawal_full_repayment_zero_net_invariant
        """
        worker, entitled = _setup_two_payment_claim(api)
        before = list_payments(entitled["id"])
        assert sum(p["net_paid_cents"] for p in before) == 29_220

        set_clock("2027-05-15T00:00:00Z")  # month 11 after entitlement
        withdrawn = validate_success(
            api.withdraw_claim(entitled["id"], 29_220, make_claimant_headers(worker["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["total_paid_cents"] == 0
        assert withdrawn["monthly_benefit_cents"] == 0

        after = list_payments(entitled["id"])
        assert len(after) == 2, "payments remain queryable"
        assert all(p["status"] == "REPAYED" for p in after)

        worker_fresh = get_worker(worker["id"])
        assert worker_fresh["withdrawal_used"] is True

    def test_withdrawn_claim_does_not_block_refile(self, api):
        """PRD §3.6: "The withdrawn claim is treated as never filed: the worker
        may file a fresh claim — the duplicate-active-claim guard does not see
        terminal claims — but may never withdraw again."

        Design: Difficulty/compensating_invariant/withdrawal_full_repayment_zero_net_invariant
        """
        worker, entitled = _setup_two_payment_claim(api)
        set_clock("2027-05-15T00:00:00Z")
        validate_success(
            api.withdraw_claim(entitled["id"], 29_220, make_claimant_headers(worker["id"]))
        )

        refiled = file_claim(worker["id"], "RETIREMENT", "2027-06")
        assert refiled["status"] == "FILED"
        assert refiled["id"] != entitled["id"]


class TestStateBeatsTemporal:
    def test_withdraw_denied_claim_past_window_is_invalid_state(self, api):
        """PRD §2.9: "When several rules could reject the same request, the
        system evaluates them in a fixed order and the **first failure wins** —
        later checks are not consulted once an earlier one has rejected."
        PRD §2.9 layer 6: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."
        PRD §3.6: "It is available only from `ENTITLED` — `ENTITLED →
        WITHDRAWN`."

        A withdrawal against a DENIED claim 16 months after entitlement violates
        both the state gate and the 12-month window; the state check wins.

        Design: Difficulty/priority_pair_validation_conflict/withdraw_state_error_beats_temporal_error
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Priority Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        validate_success(
            api.deny_claim(claim["id"], "insufficient insured status",
                           make_claims_specialist_headers("spec-1"))
        )

        set_clock("2027-10-01T00:00:00Z")
        resp = api.withdraw_claim(claim["id"], 0, make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        unchanged = get_claim(claim["id"])
        assert unchanged["status"] == "DENIED"
        assert list_payments(claim["id"]) == []

    def test_withdraw_entitled_claim_past_window_is_temporal_error(self, api):
        """PRD §3.6: "No more than twelve months may separate `entitlement_month`
        from the current logical month, else `ERR_WITHDRAWAL_WINDOW_EXPIRED`
        (422)."

        With the state gate satisfied (ENTITLED), the temporal layer is the one
        that fires — confirming the losing error of the priority pair is
        reachable on its own.

        Design: Difficulty/priority_pair_validation_conflict/withdraw_state_error_beats_temporal_error
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")

        set_clock("2027-10-01T00:00:00Z")
        resp = api.withdraw_claim(entitled["id"], 0, make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_WINDOW_EXPIRED, 422)

        unchanged = get_claim(entitled["id"])
        assert unchanged["status"] == "ENTITLED"
