"""Depth tests: non-linear state machines and transitive cascades."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    QA_PHARMACIST_HEADERS,
    assert_lot_quantity_conservation,
)
from test_helpers import fixtures


class TestSiteQualificationCycle:
    """QUALIFIED -> SUSPENDED -> QUALIFIED is a repeatable cycle."""

    def test_qualified_suspended_reinstated_back_to_qualified(self, api):
        """PRD §3.3: "A `QUALIFIED` site may be suspended by a
        `ComplianceOfficer`, moving it to `SUSPENDED`; the request body must carry
        `expected_site_version` matching the site's current `version`, and a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in
        §2.6."
        PRD §3.3: "A `SUSPENDED` site may be reinstated to `QUALIFIED` by a
        `ComplianceOfficer`, again requiring `active_license_count` of at least
        one."

        Design: Difficulty/non_linear_state_machine/site_qualification_cycle_qualified_suspended_qualified
        """
        fixtures.set_clock(api)
        site = fixtures.setup_qualified_site(api, organization_name="Cycle Clinic")
        suspended = get_success_data(
            api.suspend_site(
                site["id"], {"expected_site_version": site["version"]},
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert suspended["qualification_status"] == "SUSPENDED"
        reinstated = get_success_data(api.reinstate_site(site["id"], COMPLIANCE_OFFICER_HEADERS))
        assert reinstated["qualification_status"] == "QUALIFIED"

    def test_cycle_increments_version_each_transition(self, api):
        """PRD §2.5: "`version` — an integer starting at 1 that increments by 1
        on every mutation."
        PRD §3.3: "On qualification, `qualified_at` is stamped from the logical
        clock and the site's `version` increments."

        Design: Difficulty/non_linear_state_machine/site_qualification_cycle_qualified_suspended_qualified
        """
        fixtures.set_clock(api)
        site = fixtures.setup_qualified_site(api, organization_name="Cycle Clinic")
        v_after_qualify = site["version"]
        suspended = get_success_data(
            api.suspend_site(
                site["id"], {"expected_site_version": v_after_qualify},
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert suspended["version"] == v_after_qualify + 1
        reinstated = get_success_data(api.reinstate_site(site["id"], COMPLIANCE_OFFICER_HEADERS))
        assert reinstated["version"] == v_after_qualify + 2, (
            f"suspend + reinstate must each bump version by 1: "
            f"{v_after_qualify} -> {suspended['version']} -> {reinstated['version']}"
        )


class TestShipmentForkJoin:
    """PACKING forks on is_international; both branches rejoin at READY_TO_DISPATCH."""

    def _finalize_for(self, api, lot, site, ndc="N1", quantity=5):
        request = fixtures.create_request(api, site["id"], quantity_requested=quantity, ndc_code=ndc)
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": quantity}]
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        return fixtures.get_decision(api, decision["id"])

    def _setup(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        site_domestic = fixtures.setup_qualified_site(
            api, organization_name="US Clinic", country_code="US"
        )
        site_international = fixtures.setup_qualified_site(
            api, organization_name="Haiti Clinic", country_code="HT", underserved_index=0.9
        )
        return donor, lot, site_domestic, site_international

    def test_domestic_shipment_goes_straight_to_ready_to_dispatch(self, api):
        """PRD §3.7: "From `PACKING`, an international shipment advances to
        `AWAITING_CUSTOMS_DOCS`; a domestic one advances directly to
        `READY_TO_DISPATCH`."

        Design: Difficulty/non_linear_state_machine/shipment_fork_join_international_vs_domestic_paths
        """
        _, lot, site_domestic, _ = self._setup(api)
        decision = self._finalize_for(api, lot, site_domestic)
        shipment = fixtures.create_shipment_for_decision(api, decision["id"])
        packed = get_success_data(
            api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        assert packed["status"] == "READY_TO_DISPATCH"
        assert packed["is_international"] is False

    def test_international_shipment_waits_for_customs(self, api):
        """PRD §3.7: "From `PACKING`, an international shipment advances to
        `AWAITING_CUSTOMS_DOCS`; a domestic one advances directly to
        `READY_TO_DISPATCH`."
        PRD §3.1/§3.3: "The boolean `is_international` is derived: it is true
        exactly when `country_code` is not `US`."

        Design: Difficulty/non_linear_state_machine/shipment_fork_join_international_vs_domestic_paths
        """
        _, lot, _, site_international = self._setup(api)
        decision = self._finalize_for(api, lot, site_international)
        shipment = fixtures.create_shipment_for_decision(api, decision["id"])
        packed = get_success_data(
            api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        assert packed["status"] == "AWAITING_CUSTOMS_DOCS"
        assert packed["is_international"] is True


class TestLicenseExpiryCascade:
    """Clock advance expires the license, suspends the site, cancels requests,
    releases lines, and restores the lot's counters."""

    def _setup(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        site = fixtures.create_site(api, organization_name="Expiry Clinic")
        lic = fixtures.create_verified_license(
            api, site["id"], expires_on="2026-09-15T00:00:00Z",
            license_number="L-EXP-1",
        )
        get_success_data(api.qualify_site(site["id"], COMPLIANCE_OFFICER_HEADERS))
        site = fixtures.get_site(api, site["id"])
        # Open SUBMITTED request (never reviewed).
        req1 = fixtures.create_request(api, site["id"], quantity_requested=20, ndc_code="N1")
        # Second request carried through to a FINALIZED decision.
        req2 = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="N1")
        fixtures.begin_review(api, req2["id"])
        current = fixtures.get_request(api, req2["id"])
        decision = fixtures.create_draft_decision(
            api, req2["id"], [{"lot_id": lot["id"], "quantity": 10}]
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        return donor, lot, site, lic, req1, req2, decision

    def test_clock_advance_expires_license_and_suspends_site(self, api):
        """PRD §3.3: "if a license expiry causes a `QUALIFIED` site's
        `active_license_count` to drop to zero, the site automatically transitions
        to `SUSPENDED`, carrying the standard suspension cascade with it."
        PRD §3.3: "When the logical clock reaches a `VERIFIED` license's
        `expires_on`, the license automatically transitions to the terminal
        `EXPIRED` status."

        Design: Difficulty/transitive_cascade/license_expiry_cascades_to_site_suspension_and_request_cancellation
        """
        _, _, site, lic, _, _, _ = self._setup(api)
        fixtures.set_clock(api, "2026-09-16T00:00:00Z")
        lic_after = get_success_data(api.get_license(lic["id"], COMPLIANCE_OFFICER_HEADERS))
        assert lic_after["verification_status"] == "EXPIRED"
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["active_license_count"] == 0
        assert site_after["qualification_status"] == "SUSPENDED"

    def test_cascade_cancels_requests_and_releases_lot_quantity(self, api):
        """PRD §3.3: "Suspension cascades: every `AllocationRequest` for the site
        in `SUBMITTED` or `UNDER_REVIEW` transitions to `CANCELLED`, and every
        `AllocationLine` in `RESERVED` for the site transitions to `RELEASED`
        with the corresponding lots' `quantity_committed` decreased and
        `quantity_available` increased."

        Design: Difficulty/transitive_cascade/license_expiry_cascades_to_site_suspension_and_request_cancellation
        """
        _, lot, site, _, req1, req2, decision = self._setup(api)
        fixtures.set_clock(api, "2026-09-16T00:00:00Z")
        req1_after = get_success_data(
            api.get_allocation_request(req1["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert req1_after["status"] == "CANCELLED"
        lines = fixtures.list_lines_for_decision(api, decision["id"])
        assert all(line["status"] == "RELEASED" for line in lines), (
            f"reserved lines must be RELEASED, got {[l['status'] for l in lines]}"
        )
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["quantity_committed"] == 0
        assert lot_after["quantity_available"] == 100
        assert_lot_quantity_conservation(lot_after)


class TestLotRecallCascade:
    """A QA recall releases reserved lines and cancels in-packing shipments."""

    def _setup(self, api):
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(api, quantity_requested=10, lot_quantity=100)
        shipment = fixtures.create_shipment_for_decision(api, world["decision"]["id"])
        world["shipment"] = shipment
        return world

    def test_recall_cancels_packing_shipment(self, api):
        """PRD §3.2: "Recall has cascading consequences: every `AllocationLine`
        against this lot that is still in `RESERVED` status transitions to
        `RELEASED` (with each lot's `quantity_committed` decremented accordingly
        and the released units returning to `quantity_available`), and every
        `Shipment` in `PACKING` or `READY_TO_DISPATCH` containing lines against
        this lot transitions to `CANCELLED`."

        Design: Difficulty/transitive_cascade/lot_recall_cascades_release_lines_and_cancels_packing_shipment
        """
        world = self._setup(api)
        get_success_data(api.recall_lot(world["lot"]["id"], QA_PHARMACIST_HEADERS))
        shipment_after = fixtures.get_shipment(api, world["shipment"]["id"])
        assert shipment_after["status"] == "CANCELLED"

    def test_recall_zeroes_available_and_committed(self, api):
        """PRD §3.2: "The lot's `quantity_available` is recomputed and falls to
        zero for any non-shipped units; the lot's `version` increments by 1."
        PRD §3.2: "A recall, also executed by a `QAPharmacist`, moves a lot from
        either `QUARANTINED` or `RELEASABLE` into the terminal `RECALLED`
        posture."

        Design: Difficulty/transitive_cascade/lot_recall_cascades_release_lines_and_cancels_packing_shipment
        """
        world = self._setup(api)
        recalled = get_success_data(api.recall_lot(world["lot"]["id"], QA_PHARMACIST_HEADERS))
        assert recalled["lot_posture"] == "RECALLED"
        lot_after = fixtures.get_lot(api, world["lot"]["id"])
        assert lot_after["quantity_available"] == 0
        assert lot_after["quantity_committed"] == 0
