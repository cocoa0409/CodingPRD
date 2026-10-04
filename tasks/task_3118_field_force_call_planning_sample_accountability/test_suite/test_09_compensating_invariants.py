"""Compensating invariants: paired forward/compensation actions leave the
conserved quantities without drift.

Queue A — difficulty design rule ``compensating_invariant``.
"""

from test_helpers import (
    get_success_data,
    make_field_rep_headers,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestTransferAcceptReverseConservation:
    """Accept of 12 paired with its reverse leaves every balance component
    and the lot-level issued total exactly as before."""

    def _setup(self, api):
        ctx = fx.setup_two_reps_with_lot(
            api, sender_issued=30, receiver_issued=5, lot_quantity=100
        )
        transfer = fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 12
        )
        get_success_data(
            api.accept_transfer(
                transfer["id"],
                headers=make_field_rep_headers(ctx["receiver"]["id"]),
            )
        )
        get_success_data(
            api.reverse_transfer(transfer["id"], headers=COMPLIANCE_HEADERS)
        )
        ctx["transfer"] = transfer
        return ctx

    def test_sender_balance_restored_exactly(self, api):
        """PRD section 3.6: "a ComplianceOfficer may reverse an ACCEPTED transfer
        while the lot remains RELEASED: the sender's qty_transferred_out and the
        receiver's qty_transferred_in each decrease by the quantity, restoring both
        balances, and the conservation invariant is re-verified."

        Design: Difficulty/compensating_invariant/transfer_accept_reverse_preserves_field_force_total_units
        """
        ctx = self._setup(api)
        balance = get_success_data(
            api.get_lot_balance(
                ctx["sender_balance"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert balance["qty_issued"] == 30
        assert balance["qty_transferred_out"] == 0
        assert balance["qty_in_transit_out"] == 0
        assert balance["qty_available_forward"] == 30

    def test_field_force_total_units_unchanged(self, api):
        """PRD section 2.8: "A conservation invariant holds across the field force for
        each lot: the sum of units in all representatives' custody changes only
        through issuance from the lot, dispensation at a signed visit, return, or
        destruction — a transfer accept moves units between two reps' balances
        without changing their total, and the system re-verifies this invariant on
        both transfer acceptance and transfer reversal."

        Design: Difficulty/compensating_invariant/transfer_accept_reverse_preserves_field_force_total_units
        """
        ctx = self._setup(api)
        rows, _meta = validate_paginated(
            api.list_lot_balances(
                headers=COMPLIANCE_HEADERS, params={"lot_id": ctx["lot"]["id"]}
            )
        )
        total_issued = sum(r["qty_issued"] for r in rows)
        assert total_issued == 35
        receiver = get_success_data(
            api.get_lot_balance(
                ctx["receiver_balance"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert receiver["qty_transferred_in"] == 0
        assert receiver["qty_available_forward"] == 5


class TestVoidedDisbursementReleasesReservation:
    """A PENDING_SIGNATURE disbursement VOIDED by a visit cancel releases its
    reservation: rep availability and lot accounting both return exactly."""

    def _setup(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api,
            tier="B",
            planned_sample_units=30,
            budget=200,
            rep_issue_qty=40,
            lot_quantity=100,
        )
        visit = fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-09-05T08:00:00Z",
            scheduled_end="2026-09-05T09:00:00Z",
        )
        disbursement = get_success_data(
            api.create_sample_disbursement(
                f.create_sample_disbursement_payload(
                    visit["id"], ctx["lot"]["id"], 6
                ),
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        get_success_data(
            api.cancel_call_visit(
                visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
            )
        )
        ctx["visit"] = visit
        ctx["disbursement"] = disbursement
        return ctx

    def test_disbursement_voided_and_reservation_released(self, api):
        """PRD section 3.4: "cancellation voids every PENDING_SIGNATURE disbursement
        on the visit, releasing the reserved quantities back into the rep's available
        balances."

        Design: Difficulty/compensating_invariant/disbursement_sign_then_void_via_visit_cancel_preserves_lot_accounting
        """
        ctx = self._setup(api)
        disbursement = get_success_data(
            api.get_sample_disbursement(
                ctx["disbursement"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert disbursement["reconciliation_status"] == "VOIDED"
        balance = get_success_data(
            api.get_lot_balance(ctx["balance"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert balance["qty_available_forward"] == 40

    def test_lot_level_identity_holds(self, api):
        """PRD section 3.2: "The lot's quantity_available is derived as
        quantity_received minus units issued, minus units destroyed, minus units
        expired into quarantine, minus units returned to the manufacturer."

        Design: Difficulty/compensating_invariant/disbursement_sign_then_void_via_visit_cancel_preserves_lot_accounting
        """
        ctx = self._setup(api)
        lot = get_success_data(
            api.get_sample_lot(ctx["lot"]["id"], headers=COMPLIANCE_HEADERS)
        )
        # 100 received, 40 issued, nothing dispensed/destroyed/returned:
        # available stays 60 — the voided reservation leaked nothing.
        assert lot["quantity_available"] == 60
