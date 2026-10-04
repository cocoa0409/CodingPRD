"""Endpoint corner coverage: the logical clock endpoint, the transfer accept
action endpoint, and the destruction report reference minting.

Queue B — corner design section ``endpoints``.
"""

import re

from test_helpers import (
    get_success_data,
    make_field_rep_headers,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN_HEADERS, COMPLIANCE_HEADERS


class TestLogicalClock:
    def test_clock_set_round_trips(self, api):
        """PRD section 2.5: "The clock is advanced only through an admin-only
        test-driving capability that accepts a to_iso8601 timestamp and returns the
        current logical time as current_utc."

        Design: Corner/endpoints/clock_set_endpoint_round_trips_logical_time
        """
        data = fx.set_clock(api, "2026-10-15T12:30:00Z")
        assert str(data["current_utc"]).startswith("2026-10-15T12:30:00")


class TestTransferAcceptAction:
    def _setup_requested_transfer(self, api):
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=20, lot_quantity=50)
        transfer = fx.request_transfer(
            api, ctx["sender"], ctx["receiver"], ctx["lot"], 6
        )
        ctx["transfer"] = transfer
        return ctx

    def test_accept_moves_state_and_sender_balance(self, api):
        """PRD section 3.6: "On acceptance the sender's qty_transferred_out increases
        by the quantity while their qty_in_transit_out decreases by the same amount,
        and the receiver's qty_transferred_in increases by the quantity."

        Design: Corner/endpoints/transfer_accept_action_endpoint_moves_state_and_balances
        """
        ctx = self._setup_requested_transfer(api)
        data = get_success_data(
            api.accept_transfer(
                ctx["transfer"]["id"],
                headers=make_field_rep_headers(ctx["receiver"]["id"]),
            )
        )
        assert data["status"] == "ACCEPTED"
        balance = get_success_data(
            api.get_lot_balance(
                ctx["sender_balance"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert balance["qty_transferred_out"] == 6
        assert balance["qty_in_transit_out"] == 0
        assert balance["qty_available_forward"] == 14

    def test_accept_credits_receiver_balance(self, api):
        """PRD section 3.6: "On acceptance the sender's qty_transferred_out increases
        by the quantity while their qty_in_transit_out decreases by the same amount,
        and the receiver's qty_transferred_in increases by the quantity; the
        conservation invariant of §2.8 is verified — total field-force units for the
        lot are unchanged."

        Design: Corner/endpoints/transfer_accept_action_endpoint_moves_state_and_balances
        """
        ctx = self._setup_requested_transfer(api)
        fx_accept = api.accept_transfer(
            ctx["transfer"]["id"],
            headers=make_field_rep_headers(ctx["receiver"]["id"]),
        )
        get_success_data(fx_accept)
        from test_helpers import validate_paginated

        rows, _meta = validate_paginated(
            api.list_rep_lot_balances(
                ctx["receiver"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        receiver_rows = [r for r in rows if r["lot_id"] == ctx["lot"]["id"]]
        assert receiver_rows, "receiver must hold a balance row after accept"
        receiver = receiver_rows[0]
        assert receiver["qty_transferred_in"] == 6
        assert receiver["qty_available_forward"] == 6


class TestDestructionReportReference:
    def _setup_two_submitted_returns(self, api):
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        ret1 = fx.create_draft_return(
            api, ctx["sender"], ctx["lot"]["id"], 3, return_reason="DAMAGED"
        )
        fx.submit_return(api, ret1["id"], ctx["sender"])
        ret2 = fx.create_draft_return(
            api,
            ctx["sender"],
            ctx["lot"]["id"],
            2,
            return_reason="DAMAGED",
            destruction_method="CHEMICAL_NEUTRALIZATION",
        )
        fx.submit_return(api, ret2["id"], ctx["sender"])
        ctx["ret1"] = ret1
        ctx["ret2"] = ret2
        return ctx

    def test_confirm_mints_dest_reference(self, api):
        """PRD section 3.7: "Confirmation moves the return to DESTRUCTION_CONFIRMED
        and mints a destruction_report_ref of the form DEST- followed by a
        zero-padded sequence number."

        Design: Corner/endpoints/destruction_confirm_mints_sequential_report_reference
        """
        ctx = self._setup_two_submitted_returns(api)
        data = get_success_data(
            api.confirm_destruction(ctx["ret1"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert data["status"] == "DESTRUCTION_CONFIRMED"
        assert re.match(r"^DEST-\d+$", data["destruction_report_ref"]), (
            "destruction_report_ref must be DEST- followed by a sequence number"
        )

    def test_second_confirm_mints_distinct_greater_sequence(self, api):
        """PRD section 3.7: "mints a destruction_report_ref of the form DEST- followed
        by a zero-padded sequence number" — a sequence assigns each confirmed return
        its own reference.

        Design: Corner/endpoints/destruction_confirm_mints_sequential_report_reference
        """
        ctx = self._setup_two_submitted_returns(api)
        first = get_success_data(
            api.confirm_destruction(ctx["ret1"]["id"], headers=COMPLIANCE_HEADERS)
        )
        second = get_success_data(
            api.confirm_destruction(ctx["ret2"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert first["destruction_report_ref"] != second["destruction_report_ref"]
        seq1 = int(first["destruction_report_ref"].split("-", 1)[1])
        seq2 = int(second["destruction_report_ref"].split("-", 1)[1])
        assert seq2 == seq1 + 1
