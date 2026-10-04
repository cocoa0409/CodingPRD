"""Corner tests: envelope/pagination shape, error surface, RBAC exclusivity,
and immediate consistency after finalize."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ALLOCATION_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiErrorId as E,
)
from test_helpers import fixtures


class TestPaginationDefaults:
    def test_omitted_limit_returns_default_page(self, api):
        """PRD §2.3: "The `limit` parameter sets the page size: it defaults to
        10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets
        how many records to skip and defaults to 0. The `meta` object of a
        paginated list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/pagination_defaults_applied_when_limit_offset_omitted
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        fixtures.create_lot_batch(api, donor["id"], 12, quantity_received=1)
        resp = api.list_lots(QA_PHARMACIST_HEADERS)
        data, meta = validate_paginated(resp)
        assert len(data) == 10, f"default page size is 10, got {len(data)}"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True


class TestErrorEnvelopeShape:
    def test_error_response_conforms_to_envelope(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format: { meta: { api_request_id,
        api_request_timestamp }, response_type: 'error', data: { error_id,
        message } }."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_error_shape_conforms
        """
        fixtures.set_clock(api)
        resp = api.get_lot(NON_EXISTENT_UUID, QA_PHARMACIST_HEADERS)
        body = resp.json()
        assert resp.status_code == 404
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"].strip()
        assert body["meta"].get("api_request_id")
        assert body["meta"].get("api_request_timestamp")


class TestCustomsValueInvalid:
    def test_zero_value_declaration_rejected(self, api):
        """PRD §3.7: "A declaration whose computed value is zero is rejected with
        `ERR_CUSTOMS_VALUE_INVALID` (HTTP 422)."

        Design: Corner/errors/err_customs_value_invalid_triggerable
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="Z", product_name="ZeroValue",
            quantity_received=10,
            unit_acquisition_value_usd=0.00, unit_wholesale_value_usd=0.00,
        )
        site = fixtures.setup_qualified_site(
            api, organization_name="HT", country_code="HT", underserved_index=0.9
        )
        request = fixtures.create_request(api, site["id"], quantity_requested=1, ndc_code="Z")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 1}]
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        shipment = fixtures.create_shipment_for_decision(api, decision["id"])
        get_success_data(api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS))
        licenses = api.list_licenses(
            COMPLIANCE_OFFICER_HEADERS, params={"site_id": site["id"]}
        ).json()["data"]
        declaration = get_success_data(
            api.create_customs_declaration(
                {
                    "shipment_id": shipment["id"],
                    "hs_code": "3004.90",
                    "import_license_id": licenses[0]["id"],
                },
                LOGISTICS_COORDINATOR_HEADERS,
            ),
            201,
        )
        resp = api.submit_customs_declaration(declaration["id"], LOGISTICS_COORDINATOR_HEADERS)
        validate_error(resp, E.ERR_CUSTOMS_VALUE_INVALID, 422)


class TestExclusiveRoleEndpoints:
    def test_logistics_coordinator_cannot_qualify_sites(self, api):
        """PRD §2.1: "Once authenticated, the server consults the role matrix; if
        the named role is not permitted to invoke the targeted endpoint, the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication
        precedes authorization in evaluation order."
        PRD §4: "POST `/medicine-relief/sites/{site_id}/qualify` —
        ComplianceOfficer."

        Design: Corner/rbac/logistics_coordinator_cannot_qualify_sites
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        fixtures.create_verified_license(api, site["id"], license_number="L-1")
        resp = api.qualify_site(site["id"], LOGISTICS_COORDINATOR_HEADERS)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE, 403)
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["qualification_status"] == "PENDING_REVIEW"

    def test_allocation_officer_cannot_dispatch_shipments(self, api):
        """PRD §2.1: "Once authenticated, the server consults the role matrix; if
        the named role is not permitted to invoke the targeted endpoint, the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication
        precedes authorization in evaluation order."
        PRD §4: "POST `/medicine-relief/shipments/{shipment_id}/dispatch` —
        LogisticsCoordinator."

        Design: Corner/rbac/allocation_officer_cannot_dispatch_shipments
        """
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(api, quantity_requested=1, lot_quantity=10)
        shipment = fixtures.create_shipment_for_decision(api, world["decision"]["id"])
        get_success_data(api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS))
        resp = api.dispatch_shipment(shipment["id"], ALLOCATION_OFFICER_HEADERS)
        validate_error(resp, E.ERR_FORBIDDEN_ROLE, 403)
        shipment_after = fixtures.get_shipment(api, shipment["id"])
        assert shipment_after["status"] == "READY_TO_DISPATCH"


class TestImmediateConsistency:
    def test_finalize_results_immediately_visible(self, api):
        """PRD §3.5: "On successful finalization, several things happen
        atomically. The decision moves to `FINALIZED` and `decided_at` is stamped
        from the logical clock. Every line moves to `RESERVED`, its quantity is
        added to its lot's `quantity_committed`, and each line's
        `reservation_expires_at` is set from `decided_at` plus a TTL: seventy-two
        hours for ordinary requests, shortened to twenty-four hours when the
        request's `emergency_event_id` references an `EmergencyEvent` in `ACTIVE`
        status. The request's `need_score` is computed and persisted (see §3.6).
        The request then transitions to `APPROVED` when the finalized lines
        exactly cover `quantity_requested`, or to `PARTIALLY_APPROVED` when they
        cover a positive quantity less than `quantity_requested`;
        `quantity_approved` is set to the covered amount, and the request's
        `version` increments."

        Design: Corner/consistency_model/immediate_consistency_after_decision_finalize
        """
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(api, quantity_requested=10, lot_quantity=100)
        # Immediate reads reflect the finalized state with no lag.
        request = fixtures.get_request(api, world["request"]["id"])
        assert request["status"] == "APPROVED"
        assert request["quantity_approved"] == 10
        assert request.get("need_score") is not None
        lot = fixtures.get_lot(api, world["lot"]["id"])
        assert lot["quantity_committed"] == 10
