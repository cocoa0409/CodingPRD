"""Depth tests: compensating-action invariants.

A shipment cancel restores the lot's committed/available split; a superseding
decision redistributes coverage across lots while conserving quantity_approved.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    LOGISTICS_COORDINATOR_HEADERS,
    assert_lot_quantity_conservation,
)
from test_helpers import fixtures


class TestShipmentCancelRestoresLotQuantities:
    """RESERVED -> PICKED on create, PICKED -> RESERVED on cancel."""

    def _setup(self, api):
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(api, quantity_requested=10, lot_quantity=100)
        shipment = fixtures.create_shipment_for_decision(api, world["decision"]["id"])
        world["shipment"] = shipment
        return world

    def test_create_moves_committed_to_in_flight(self, api):
        """PRD §3.7: "Every referenced line must be `RESERVED` and the decision
        `FINALIZED`; on creation each line advances from `RESERVED` to `PICKED`
        and its quantity moves out of the lot's `quantity_committed` (the units
        are now in-flight rather than reserved)."

        Design: Difficulty/compensating_invariant/shipment_cancel_restores_lot_quantity_committed_and_available
        """
        world = self._setup(api)
        lot = fixtures.get_lot(api, world["lot"]["id"])
        assert lot["quantity_committed"] == 0, (
            f"after shipment creation the line is PICKED: committed must drop 10 -> 0, "
            f"got {lot['quantity_committed']}"
        )
        lines = fixtures.list_lines_for_decision(api, world["decision"]["id"])
        assert all(line["status"] == "PICKED" for line in lines)

    def test_cancel_restores_committed_and_available(self, api):
        """PRD §3.7: "Cancellation moves it to the terminal `CANCELLED` status
        and returns every `PICKED` line to `RESERVED`, with each line's quantity
        added back to its lot's `quantity_committed`."

        Design: Difficulty/compensating_invariant/shipment_cancel_restores_lot_quantity_committed_and_available
        """
        world = self._setup(api)
        cancelled = get_success_data(
            api.cancel_shipment(world["shipment"]["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        assert cancelled["status"] == "CANCELLED"
        lot = fixtures.get_lot(api, world["lot"]["id"])
        assert lot["quantity_committed"] == 10, (
            f"cancel must restore committed 0 -> 10, got {lot['quantity_committed']}"
        )
        assert lot["quantity_available"] == 90
        assert_lot_quantity_conservation(lot)
        lines = fixtures.list_lines_for_decision(api, world["decision"]["id"])
        assert all(line["status"] == "RESERVED" for line in lines)


class TestDecisionSupersedeConservesCoverage:
    """Finalizing a second decision supersedes the first and keeps coverage."""

    def _setup(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot1 = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="N1", quantity_received=50
        )
        lot2 = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="N1", quantity_received=50,
            expiration_date="2027-08-31T00:00:00Z",
        )
        site = fixtures.setup_qualified_site(api)
        request = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="N1")
        fixtures.begin_review(api, request["id"])
        v1 = fixtures.get_request(api, request["id"])["version"]
        decision1 = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot1["id"], "quantity": 10}]
        )
        fixtures.finalize_decision(api, decision1["id"], v1)
        # Re-open the APPROVED request; all of decision1's lines are RESERVED.
        fixtures.begin_review(api, request["id"])
        v2 = fixtures.get_request(api, request["id"])["version"]
        decision2 = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot2["id"], "quantity": 10}]
        )
        return lot1, lot2, request, decision1, decision2, v2

    def test_superseding_finalize_supersedes_prior_decision(self, api):
        """PRD §3.5: "When a request in `APPROVED` or `PARTIALLY_APPROVED` is
        taken back into `UNDER_REVIEW` and a new draft is finalized, the
        previously `FINALIZED` decision transitions to the terminal `SUPERSEDED`
        status — permitted only while all of that decision's lines remain
        `RESERVED`."

        Design: Difficulty/compensating_invariant/decision_supersede_conserves_request_quantity_approved
        """
        _, _, _, decision1, decision2, v2 = self._setup(api)
        fixtures.finalize_decision(api, decision2["id"], v2)
        d1_after = fixtures.get_decision(api, decision1["id"])
        d2_after = fixtures.get_decision(api, decision2["id"])
        assert d1_after["status"] == "SUPERSEDED"
        assert d2_after["status"] == "FINALIZED"

    def test_supersede_redistributes_commitment_and_conserves_coverage(self, api):
        """PRD §3.5: "Supersession releases the old decision's lines (each to
        `RELEASED`, with lot `quantity_committed` decreased and
        `quantity_available` increased), and the request's `quantity_approved` is
        recomputed from the superseding decision."

        Design: Difficulty/compensating_invariant/decision_supersede_conserves_request_quantity_approved
        """
        lot1, lot2, request, decision1, decision2, v2 = self._setup(api)
        fixtures.finalize_decision(api, decision2["id"], v2)
        lot1_after = fixtures.get_lot(api, lot1["id"])
        lot2_after = fixtures.get_lot(api, lot2["id"])
        assert lot1_after["quantity_committed"] == 0, (
            "the superseded decision's reservation must be released"
        )
        assert lot2_after["quantity_committed"] == 10, (
            "the superseding decision's reservation must be active"
        )
        request_after = fixtures.get_request(api, request["id"])
        assert request_after["quantity_approved"] == 10, (
            f"coverage is conserved across the supersede, got {request_after['quantity_approved']}"
        )
        assert request_after["status"] == "APPROVED"
