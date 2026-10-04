"""Non-linear state machines: the transfer REVERSED cycle and the bounded
count-session reopen loop.

Queue A — difficulty design rule ``non_linear_state_machine``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestTransferAcceptReverseCycle:
    """ACCEPTED is not terminal in effect — REVERSED re-enters the ledger."""

    def test_reverse_restores_sender_balance(self, api):
        """PRD section 3.6: "a ComplianceOfficer may reverse an ACCEPTED transfer
        while the lot remains RELEASED: the sender's qty_transferred_out and the
        receiver's qty_transferred_in each decrease by the quantity, restoring both
        balances."

        Design: Difficulty/non_linear_state_machine/sample_transfer_accept_then_reverse_cycle_restores_balances
        """
        ctx = fx.setup_accepted_transfer(api, quantity=10, sender_issued=40)
        get_success_data(
            api.reverse_transfer(ctx["transfer"]["id"], headers=COMPLIANCE_HEADERS)
        )
        balance = get_success_data(
            api.get_lot_balance(
                ctx["sender_balance"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert balance["qty_transferred_out"] == 0
        assert balance["qty_in_transit_out"] == 0
        assert balance["qty_available_forward"] == 40

    def test_reverse_restores_receiver_and_marks_transfer(self, api):
        """PRD section 3.6: "The transfer's status enumeration is REQUESTED, ACCEPTED,
        REJECTED, CANCELLED, and REVERSED, with all but REQUESTED terminal."

        Design: Difficulty/non_linear_state_machine/sample_transfer_accept_then_reverse_cycle_restores_balances
        """
        ctx = fx.setup_accepted_transfer(api, quantity=10, sender_issued=40)
        get_success_data(
            api.reverse_transfer(ctx["transfer"]["id"], headers=COMPLIANCE_HEADERS)
        )
        transfer = get_success_data(
            api.get_sample_transfer(
                ctx["transfer"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert transfer["status"] == "REVERSED"
        rows, _meta = validate_paginated(
            api.list_rep_lot_balances(
                ctx["receiver"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        receiver_rows = [r for r in rows if r["lot_id"] == ctx["lot"]["id"]]
        assert receiver_rows, "receiver must hold a balance row after accept"
        receiver_balance = receiver_rows[0]
        assert receiver_balance["qty_transferred_in"] == 0
        assert receiver_balance["qty_available_forward"] == 0


class TestCountSessionReopenLoop:
    """RECONCILED -> OPEN -> COUNTED -> RECONCILED may cycle at most three
    times; the fourth reopen is refused."""

    def _setup_reopened_three_times(self, api):
        ctx = fx.setup_reconciled_session(
            api, custodian_issue_qty=20, counted_qty=20
        )
        session = ctx["session"]
        for _ in range(3):
            get_success_data(
                api.reopen_count_session(session["id"], headers=COMPLIANCE_HEADERS)
            )
            fx.submit_full_count(
                api, session["id"], ctx["counter"], {ctx["lot"]["id"]: 20}
            )
            fx.reconcile_session(api, session["id"], ctx["manager"])
        return ctx

    def test_fourth_reopen_rejected(self, api):
        """PRD section 3.6: "A session may be reopened at most three times — a fourth
        attempt is rejected with ERR_REOPEN_LIMIT_EXCEEDED."

        Design: Difficulty/non_linear_state_machine/inventory_count_session_reopen_cycle_bounded_at_three
        """
        ctx = self._setup_reopened_three_times(api)
        response = api.reopen_count_session(
            ctx["session"]["id"], headers=COMPLIANCE_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED)

    def test_session_state_unchanged_after_failed_fourth_reopen(self, api):
        """PRD section 3.6: "A ComplianceOfficer may reopen a RECONCILED session for
        rework, returning it to OPEN" — a refused reopen leaves the session in
        RECONCILED.

        Design: Difficulty/non_linear_state_machine/inventory_count_session_reopen_cycle_bounded_at_three
        """
        ctx = self._setup_reopened_three_times(api)
        api.reopen_count_session(ctx["session"]["id"], headers=COMPLIANCE_HEADERS)
        session = get_success_data(
            api.get_count_session(ctx["session"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert session["status"] == "RECONCILED"
