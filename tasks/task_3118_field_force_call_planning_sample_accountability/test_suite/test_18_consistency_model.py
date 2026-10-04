"""Consistency model: reads immediately following a mutation already reflect
the mutation's full cascade — no eventual-consistency lag.

Queue B — corner design section ``consistency_model``.
"""

from test_helpers import (
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
)
from test_helpers import fixtures as fx


class TestReadYourWriteAcrossCascade:
    def _setup_signed_disbursement(self, api):
        ctx = fx.setup_completed_visit_with_disbursement(
            api, disbursement_qty=4, rep_issue_qty=20, planned_sample_units=20
        )
        signed = fx.sign_disbursement(api, ctx["disbursement"]["id"], ctx["rep"])
        ctx["signed"] = signed
        return ctx

    def test_capture_response_and_balance_reflect_signature(self, api):
        """PRD section 3.5: "First, the rep's balance is settled: qty_dispensed
        increases by the disbursement's quantity and both availability variants are
        recomputed." PRD section 2.10: "State changes propagate along this graph
        automatically whenever their criteria are met, without an explicit client
        request on the affected entity."

        Design: Corner/consistency_model/immediate_consistency_read_your_write_across_cascade
        """
        ctx = self._setup_signed_disbursement(api)
        assert ctx["signed"]["reconciliation_status"] == "SIGNED"
        assert ctx["signed"]["signed_at"] is not None
        balance = get_success_data(
            api.get_lot_balance(
                ctx["balance"]["id"],
                headers=make_field_rep_headers(ctx["rep"]["id"]),
            )
        )
        assert balance["qty_dispensed"] == 4
        assert balance["qty_available_forward"] == 16

    def test_entry_progress_reflects_signature_immediately(self, api):
        """PRD section 3.5: "Second, the entry's delivered_sample_units increases by
        the same quantity, and if it thereby reaches or exceeds the entry's
        planned_sample_units the entry's status becomes CAP_EXHAUSTED."

        Design: Corner/consistency_model/immediate_consistency_read_your_write_across_cascade
        """
        ctx = self._setup_signed_disbursement(api)
        entry = get_success_data(
            api.get_target_list_entry(
                ctx["entry"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert entry["delivered_sample_units"] == 4
