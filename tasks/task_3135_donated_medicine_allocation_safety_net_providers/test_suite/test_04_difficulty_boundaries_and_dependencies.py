"""Depth tests: boundary precision, cross-entity state dependencies, and
temporal interval semantics (license expiry vs reservation TTL)."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    ApiErrorId as E,
)
from test_helpers import fixtures
from test_helpers.test_users import make_site_coordinator_headers


class TestOverreportBoundary:
    """Cumulative reported == delivered is allowed; one more unit is rejected."""

    def _setup_delivered_with_prior_report(self, api):
        world = fixtures.setup_delivered_shipment(api, quantity_requested=10, lot_quantity=100)
        site_id = world["site"]["id"]
        shipment_id = world["shipment"]["id"]
        rep1 = fixtures.create_report(
            api, site_id, shipment_id,
            reporting_period="2026-09",
            units_distributed=4, patients_reached=4, wastage_units=2,
        )
        fixtures.submit_report(api, rep1["id"], site_id)
        get_success_data(
            api.accept_distribution_report(rep1["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        return world, rep1

    def test_cumulative_reported_equal_to_delivered_is_allowed(self, api):
        """PRD §3.11: "At submission, an overreport guard fires: the new report's
        `units_distributed` plus `wastage_units`, added to the same two figures
        summed over every prior report for the shipment in `SUBMITTED` or
        `ACCEPTED` status, must not exceed the total delivered quantity (the sum
        of quantities on the shipment decision's lines in `DELIVERED` status). A
        breach is rejected with `ERR_OVERREPORTED` (HTTP 422); exact equality
        with the delivered quantity is allowed."

        Design: Difficulty/boundary_precision_check/overreport_equality_allowed_excess_rejected
        """
        world, _ = self._setup_delivered_with_prior_report(api)
        site_id = world["site"]["id"]
        shipment_id = world["shipment"]["id"]
        rep2 = fixtures.create_report(
            api, site_id, shipment_id,
            reporting_period="2026-10",
            units_distributed=4, patients_reached=4, wastage_units=0,
        )
        submitted = fixtures.submit_report(api, rep2["id"], site_id)
        assert submitted["status"] == "SUBMITTED", (
            f"cumulative 4+2 + 4 == 10 == delivered must be allowed, got {submitted['status']}"
        )

    def test_cumulative_reported_exceeding_delivered_by_one_is_rejected(self, api):
        """PRD §3.11: "At submission, an overreport guard fires: the new report's
        `units_distributed` plus `wastage_units`, added to the same two figures
        summed over every prior report for the shipment in `SUBMITTED` or
        `ACCEPTED` status, must not exceed the total delivered quantity (the sum
        of quantities on the shipment decision's lines in `DELIVERED` status). A
        breach is rejected with `ERR_OVERREPORTED` (HTTP 422); exact equality
        with the delivered quantity is allowed."

        Design: Difficulty/boundary_precision_check/overreport_equality_allowed_excess_rejected
        """
        world, _ = self._setup_delivered_with_prior_report(api)
        site_id = world["site"]["id"]
        shipment_id = world["shipment"]["id"]
        # Bring the cumulative total to exactly 10 first.
        rep2 = fixtures.create_report(
            api, site_id, shipment_id,
            reporting_period="2026-10",
            units_distributed=4, patients_reached=4, wastage_units=0,
        )
        fixtures.submit_report(api, rep2["id"], site_id)
        # One more unit takes the cumulative total to 11 > 10.
        rep3 = fixtures.create_report(
            api, site_id, shipment_id,
            reporting_period="2026-11",
            units_distributed=1, patients_reached=1, wastage_units=0,
        )
        resp = api.submit_distribution_report(
            rep3["id"], make_site_coordinator_headers(site_id)
        )
        validate_error(resp, E.ERR_OVERREPORTED, 422)


class TestActiveLicenseCountBoundary:
    """Qualification requires at least one active license: 0 rejects, 1 succeeds."""

    def test_qualify_with_zero_active_licenses_rejected(self, api):
        """PRD §3.3: "Moving a `PENDING_REVIEW` site to `QUALIFIED` requires at
        least one active license (otherwise `ERR_NO_VERIFIED_LICENSE`, HTTP 422)
        and, for sites whose `country_code` is not `US`, additionally requires
        that the site hold a `VERIFIED` `IMPORT` license whose expiry is strictly
        after the current logical clock (otherwise `ERR_IMPORT_LICENSE_MISSING`,
        HTTP 422)."

        Design: Difficulty/boundary_precision_check/active_license_count_zero_boundary_at_qualification
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        resp = api.qualify_site(site["id"], COMPLIANCE_OFFICER_HEADERS)
        validate_error(resp, E.ERR_NO_VERIFIED_LICENSE, 422)

    def test_qualify_after_first_verified_license_succeeds(self, api):
        """PRD §3.3: "Moving a `PENDING_REVIEW` site to `QUALIFIED` requires at
        least one active license (otherwise `ERR_NO_VERIFIED_LICENSE`, HTTP 422)
        and, for sites whose `country_code` is not `US`, additionally requires
        that the site hold a `VERIFIED` `IMPORT` license whose expiry is strictly
        after the current logical clock (otherwise `ERR_IMPORT_LICENSE_MISSING`,
        HTTP 422)."
        PRD §3.3: "Each of these transitions recomputes the site's
        `active_license_count` — the count of the site's licenses in `VERIFIED`
        status whose `expires_on` is after the current logical clock."

        Design: Difficulty/boundary_precision_check/active_license_count_zero_boundary_at_qualification
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        fixtures.create_verified_license(api, site["id"], license_number="L-1")
        qualified = get_success_data(api.qualify_site(site["id"], COMPLIANCE_OFFICER_HEADERS))
        assert qualified["qualification_status"] == "QUALIFIED"
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["active_license_count"] == 1


class TestShipmentDispatchDependsOnCustoms:
    """Dispatch is blocked until the linked declaration is CLEARED."""

    def _setup_international_awaiting_customs(self, api):
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(
            api,
            quantity_requested=10,
            lot_quantity=100,
            site_overrides={
                "organization_name": "HT Clinic",
                "country_code": "HT",
                "underserved_index": 0.9,
            },
        )
        site_id = world["site"]["id"]
        body = api.list_licenses(
            COMPLIANCE_OFFICER_HEADERS, params={"site_id": site_id}
        ).json()
        lic = body["data"][0]
        shipment = fixtures.create_shipment_for_decision(api, world["decision"]["id"])
        get_success_data(api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS))
        resp = api.create_customs_declaration(
            {
                "shipment_id": shipment["id"],
                "hs_code": "3004.90",
                "import_license_id": lic["id"],
            },
            LOGISTICS_COORDINATOR_HEADERS,
        )
        declaration = get_success_data(resp, 201)
        get_success_data(
            api.submit_customs_declaration(declaration["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        return world, shipment, declaration

    def test_dispatch_blocked_until_declaration_cleared(self, api):
        """PRD §3.7: "Dispatch moves a `READY_TO_DISPATCH` shipment to
        `DISPATCHED`. For international shipments the linked declaration must
        already be `CLEARED`, otherwise `ERR_CUSTOMS_NOT_CLEARED` (HTTP 409); and
        the destination site must still be `QUALIFIED`, otherwise
        `ERR_SITE_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_depends_on_customs_cleared
        """
        world, shipment, _ = self._setup_international_awaiting_customs(api)
        # The declaration is SUBMITTED, not yet CLEARED; the shipment is still
        # AWAITING_CUSTOMS_DOCS, so dispatch must fail.
        resp = api.dispatch_shipment(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        body = resp.json()
        assert resp.status_code in (409,), (
            f"dispatch before customs clearance must fail with 409, got {resp.status_code}: {body}"
        )
        assert body["data"]["error_id"] in (
            E.ERR_CUSTOMS_NOT_CLEARED.value,
            E.ERR_INVALID_STATE.value,
        ), (
            "the PRD blocks dispatch until clearance either via the customs guard "
            "or because the shipment has not reached READY_TO_DISPATCH"
        )

    def test_clearance_advances_shipment_and_allows_dispatch(self, api):
        """PRD §3.7: "A `ComplianceOfficer` then clears the declaration — moving
        it to the terminal `CLEARED` status, which advances the shipment from
        `AWAITING_CUSTOMS_DOCS` to `READY_TO_DISPATCH`."
        PRD §3.7: "On dispatch, `dispatched_at` is stamped and every `PICKED`
        line advances to `SHIPPED`, with each line's quantity added to its lot's
        `quantity_shipped`."

        Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_depends_on_customs_cleared
        """
        _, shipment, declaration = self._setup_international_awaiting_customs(api)
        get_success_data(
            api.clear_customs_declaration(declaration["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        shipment_after_clear = fixtures.get_shipment(api, shipment["id"])
        assert shipment_after_clear["status"] == "READY_TO_DISPATCH"
        dispatched = get_success_data(
            api.dispatch_shipment(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched.get("dispatched_at"), "dispatched_at must be stamped on dispatch"


class TestFinalizeDependsOnSiteQualification:
    """Suspending the site between draft and finalize blocks finalization."""

    def _setup(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        site = fixtures.setup_qualified_site(api)
        request = fixtures.create_request(api, site["id"], quantity_requested=5, ndc_code="N1")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 5}]
        )
        return lot, site, request, decision, current["version"]

    def test_finalize_after_site_suspension_rejected(self, api):
        """PRD §3.5: "The referenced request's site must be `QUALIFIED` at both
        draft creation and finalization, otherwise `ERR_SITE_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/allocation_finalize_depends_on_site_qualification
        """
        _, site, request, decision, req_version = self._setup(api)
        site_now = fixtures.get_site(api, site["id"])
        suspended = get_success_data(
            api.suspend_site(
                site["id"],
                {"expected_site_version": site_now["version"]},
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert suspended["qualification_status"] == "SUSPENDED"
        # Re-fetch the request version: suspension cancels the UNDER_REVIEW
        # request, bumping its version. We pass the current version so that the
        # only guard that can fire is the site-qualification gate (the PRD does
        # not fix a precedence between ERR_SITE_NOT_QUALIFIED and
        # ERR_STALE_VERSION).
        req_now = fixtures.get_request(api, request["id"])
        resp = api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_now["version"]},
            fixtures.ALLOCATION_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_SITE_NOT_QUALIFIED, 409)

    def test_rejected_finalize_keeps_decision_draft(self, api):
        """PRD §3.5: "A draft's lines carry no reservation yet — quantities are
        not committed against any lot until finalization."

        Design: Difficulty/cross_entity_state_dependency/allocation_finalize_depends_on_site_qualification
        """
        lot, site, _, decision, req_version = self._setup(api)
        site_now = fixtures.get_site(api, site["id"])
        get_success_data(
            api.suspend_site(
                site["id"],
                {"expected_site_version": site_now["version"]},
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        api.finalize_decision(
            decision["id"],
            {"expected_request_version": req_version},
            fixtures.ALLOCATION_OFFICER_HEADERS,
        )
        decision_after = fixtures.get_decision(api, decision["id"])
        assert decision_after["status"] == "DRAFT"
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["quantity_committed"] == 0


class TestLicenseExpiryStrictComparison:
    """A license is verifiable iff expires_on is strictly after the clock."""

    def test_expires_on_equal_to_clock_rejected(self, api):
        """PRD §3.3: "A `ComplianceOfficer` then either verifies the license —
        possible only while it is `PENDING` and its `expires_on` is strictly
        after the current logical clock, otherwise `ERR_LICENSE_EXPIRED`
        (HTTP 422) — or rejects it."

        Design: Difficulty/resource_temporal_overlap/license_expiration_interval_vs_logical_clock
        """
        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        site = fixtures.create_site(api)
        lic = fixtures.create_license(
            api, site["id"], license_number="L-edge", expires_on="2026-09-15T00:00:00Z"
        )
        resp = api.verify_license(lic["id"], COMPLIANCE_OFFICER_HEADERS)
        validate_error(resp, E.ERR_LICENSE_EXPIRED, 422)

    def test_expires_on_one_second_after_clock_verified(self, api):
        """PRD §3.3: "A `ComplianceOfficer` then either verifies the license —
        possible only while it is `PENDING` and its `expires_on` is strictly
        after the current logical clock, otherwise `ERR_LICENSE_EXPIRED`
        (HTTP 422) — or rejects it."
        PRD §3.3: "Each of these transitions recomputes the site's
        `active_license_count` — the count of the site's licenses in `VERIFIED`
        status whose `expires_on` is after the current logical clock."

        Design: Difficulty/resource_temporal_overlap/license_expiration_interval_vs_logical_clock
        """
        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        site = fixtures.create_site(api)
        lic = fixtures.create_license(
            api, site["id"], license_number="L-ok", expires_on="2026-09-15T00:00:01Z"
        )
        verified = get_success_data(api.verify_license(lic["id"], COMPLIANCE_OFFICER_HEADERS))
        assert verified["verification_status"] == "VERIFIED"
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["active_license_count"] == 1


class TestReservationTtlForfeitureBoundary:
    """A RESERVED line forfeits when the clock reaches reservation_expires_at."""

    def _setup_reserved_line(self, api):
        world = fixtures.setup_finalized_decision(
            api, quantity_requested=10, lot_quantity=100
        )
        return world

    def test_line_still_reserved_one_second_before_expiry(self, api):
        """PRD §3.8: "When the logical clock passes a `RESERVED` line's
        `reservation_expires_at`, the line automatically transitions to the
        terminal `FORFEITED` status: the quantity is removed from the lot's
        `quantity_committed` and returned to `quantity_available`, and the parent
        request's `quantity_approved` is recomputed."

        Design: Difficulty/resource_temporal_overlap/reservation_ttl_forfeiture_at_exact_boundary
        """
        world = self._setup_reserved_line(api)
        lot_id = world["lot"]["id"]
        # Finalize happened at 2026-09-01T00:00:00Z; 72h TTL -> expiry at
        # 2026-09-04T00:00:00Z. One second earlier the line is still RESERVED.
        fixtures.set_clock(api, "2026-09-03T23:59:59Z")
        lines = fixtures.list_lines_for_decision(api, world["decision"]["id"])
        assert all(line["status"] == "RESERVED" for line in lines)
        lot = fixtures.get_lot(api, lot_id)
        assert lot["quantity_committed"] == 10

    def test_line_forfeited_at_exact_expiry_and_request_rejected(self, api):
        """PRD §3.8: "When the logical clock passes a `RESERVED` line's
        `reservation_expires_at`, the line automatically transitions to the
        terminal `FORFEITED` status: the quantity is removed from the lot's
        `quantity_committed` and returned to `quantity_available`, and the parent
        request's `quantity_approved` is recomputed. If forfeiture leaves the
        request with zero approved units, the request itself transitions to the
        terminal `REJECTED` status."

        Design: Difficulty/resource_temporal_overlap/reservation_ttl_forfeiture_at_exact_boundary
        """
        world = self._setup_reserved_line(api)
        lot_id = world["lot"]["id"]
        fixtures.set_clock(api, "2026-09-04T00:00:00Z")
        lines = fixtures.list_lines_for_decision(api, world["decision"]["id"])
        assert all(line["status"] == "FORFEITED" for line in lines), (
            f"at the TTL boundary the line must be FORFEITED, got {[l['status'] for l in lines]}"
        )
        lot = fixtures.get_lot(api, lot_id)
        assert lot["quantity_committed"] == 0
        assert lot["quantity_available"] == 100
        request = fixtures.get_request(api, world["request"]["id"])
        assert request["quantity_approved"] == 0
        assert request["status"] == "REJECTED"
