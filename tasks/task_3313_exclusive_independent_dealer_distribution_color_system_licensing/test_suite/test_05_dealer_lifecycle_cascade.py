"""Dealer termination cascade and co-op forfeiture."""
from test_helpers import (
    CD,
    RM,
    ApiErrorId,
    api_client,
    place_order,
    setup_onboarded_dealer,
    validate_error,
    validate_success,
)


class TestDealerTerminateCascade:
    def test_terminate_revokes_license_and_zeroes_coop(self, api):
        """PRD section 3.4: "Terminating a dealer cascades across every
        dependent aggregate: all of the dealer's licenses in `PENDING`,
        `ACTIVE`, `EXPIRED`, or `SUSPENDED` move to `REVOKED`; all equipment
        units not already `DECOMMISSIONED` are decommissioned; all of the
        dealer's orders in `SUBMITTED` or `APPROVED` are `CANCELLED`; all of
        the dealer's `ACTIVE` contractor accounts are `CLOSED`; the dealer's
        `coop_balance_cents` and `coop_pending_cents` are both set to 0,
        forfeiting the co-op fund; `inventory_minimum_met` resets to false;
        and the region's `active_dealer_count` decrements by 1."

        Design: Difficulty/transitive_cascade/dealer_terminate_depth3_cascade_and_coop_forfeit
        """
        ctx = setup_onboarded_dealer(
            line_overrides={"code": "S1T", "base_price_cents": 1000},
            pay_stock=True,
        )
        dealer_id = ctx["dealer"]["id"]
        # 40 units x 1000 cents x 0.02 = 800 cents accrued at payment.
        before = validate_success(api.get_dealer(dealer_id, RM))
        assert before["coop_balance_cents"] == 800
        validate_success(api.terminate_dealer(dealer_id, CD))
        lic = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert lic["status"] == "REVOKED"
        after = validate_success(api.get_dealer(dealer_id, RM))
        assert after["status"] == "TERMINATED"
        assert after["coop_balance_cents"] == 0
        assert after["coop_pending_cents"] == 0

    def test_terminate_cancels_open_orders(self, api):
        """PRD section 3.4: "Terminating a dealer cascades across every
        dependent aggregate: ... all of the dealer's orders in `SUBMITTED` or
        `APPROVED` are `CANCELLED` ...".
        PRD section 3.5: "An order in `SUBMITTED` or `APPROVED` may be
        cancelled to `CANCELLED` by the owning `DealerPrincipal`, and open
        orders in those two states are cancelled automatically when the
        dealer is terminated."

        Design: Difficulty/transitive_cascade/dealer_terminate_depth3_cascade_and_coop_forfeit
        """
        ctx = setup_onboarded_dealer(pay_stock=True)
        dealer_id = ctx["dealer"]["id"]
        open_order = place_order(dealer_id, ctx["line"]["id"], units=10, purpose="RESTOCK")
        assert open_order["status"] == "SUBMITTED"
        validate_success(api.terminate_dealer(dealer_id, CD))
        order = validate_success(api.get_order(open_order["id"], RM))
        assert order["status"] == "CANCELLED"


class TestTerminalLockdown:
    def test_suspend_on_terminated_dealer_rejected(self, api):
        """PRD section 3.4: "Termination is final and is available from
        either `ACTIVE` or `SUSPENDED`."
        PRD section 2.5: "(5) transition validity — the target resource is in
        a state from which the requested transition exists, else
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/terminate_terminal_lockdown_blocks_suspend
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        validate_success(api.terminate_dealer(dealer_id, CD))
        resp = api.suspend_dealer(dealer_id, CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reinstate_on_terminated_dealer_rejected(self, api):
        """PRD section 3.4: "Termination is final and is available from
        either `ACTIVE` or `SUSPENDED`."
        PRD section 2.5: "(5) transition validity — the target resource is in
        a state from which the requested transition exists, else
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/terminate_terminal_lockdown_blocks_suspend
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        validate_success(api.terminate_dealer(dealer_id, CD))
        resp = api.reinstate_dealer(dealer_id, CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
