"""Catalog services and statutory authorizations: field round-trip, required
fields, inherited defaults, code uniqueness, coverage gate, closed-window
authorization overlap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_service,
    api_client,
    assert_service,
    create_agency,
    create_approved_authorization,
    create_authorization,
    create_service,
    create_service_payload,
    deactivate_service,
    get_service,
    make_agency_admin_headers,
    set_clock,
    setup_active_agency,
    setup_cf_checkout,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]
AA_LEAD = make_agency_admin_headers("aa-lead")


class TestServiceCrud:
    def test_service_get_round_trips_all_fields(self, api):
        """PRD §3.2: "An `AgencyAdmin` drafts a catalog service with
        `agency_id`, a `service_code`, a display `name`, the non-empty
        `allowed_methods` subset drawn from `CARD`, `ECHECK` and `WALLET`,
        the inclusive amount bounds `min_amount_cents` and `max_amount_cents`,
        and the agency general-ledger `gl_code` that will be stamped on
        reconciliation lines."

        Design: Corner/entities/service_get_round_trips_all_fields
        """
        ctx = setup_cf_checkout(with_payer=False)
        service = get_service(ctx["service"]["id"])
        assert_service(service)
        assert service["service_code"] == "DL-RENEW"
        assert service["name"] == "Driver License Renewal"
        assert service["fee_model"] == "CONVENIENCE_FEE"
        assert service["allowed_methods"] == ["CARD", "ECHECK", "WALLET"]
        assert service["min_amount_cents"] == 100
        assert service["max_amount_cents"] == 1000000
        assert service["gl_code"] == "4110"
        assert service["status"] == "ACTIVE"
        assert service["version"] == 2, "create made version 1; activation bumped it to 2"

    def test_service_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "a request with a missing required field, a malformed
        value, an out-of-enum value, or a non-positive amount is rejected as
        malformed with `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/service_create_missing_required_field_returns_invalid_request
        """
        set_clock()
        agency = create_agency()
        payload = create_service_payload(agency["id"], allowed_methods=["CARD"])
        payload.pop("gl_code")  # gl_code is a required input with no default
        resp = api_client.create_service(payload, AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, _ = validate_paginated(api_client.list_services(agency["id"], PA))
        assert data == []

    def test_service_fee_model_defaults_to_agency_default(self, api):
        """PRD §3.2: "The `fee_model` may be omitted, in which case the
        service inherits the agency's `default_fee_model`; when present it is
        `CONVENIENCE_FEE` or `ABSORBED`. New services are born `DRAFT`."

        Design: Corner/entities/service_fee_model_defaults_to_agency_default
        """
        set_clock()
        agency = create_agency(
            legal_name="County Treasurer", agency_type="LOCAL", default_fee_model="ABSORBED"
        )
        payload = create_service_payload(
            agency["id"],
            service_code="PROP-TAX",
            name="Property Tax Payment",
            allowed_methods=["ECHECK"],
            min_amount_cents=1,
            max_amount_cents=100000000,
            gl_code="5200",
        )
        assert "fee_model" not in payload
        resp = api_client.create_service(payload, AA_LEAD)
        service = validate_success(resp, 201)
        assert service["fee_model"] == "ABSORBED", "inherited from the agency default"
        assert service["status"] == "DRAFT"

    def test_service_create_with_unknown_agency_returns_agency_not_found(self, api):
        """PRD §2.8: "Path identifiers resolve first, left to right, then
        body foreign keys in the endpoint's declared input order. Each
        unresolved reference reports its own resource's not-found error, all
        HTTP 404: `ERR_AGENCY_NOT_FOUND`".

        Design: Corner/entities/service_create_with_unknown_agency_returns_agency_not_found
        """
        set_clock()
        payload = create_service_payload(
            "00000000-0000-4000-8000-000000000001",
            service_code="X",
            name="Ghost",
            fee_model="ABSORBED",
            allowed_methods=["CARD"],
            min_amount_cents=1,
            max_amount_cents=100,
            gl_code="9",
        )
        resp = api_client.create_service(payload, AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_FOUND)

    def test_duplicate_service_code_reuse_after_deactivate(self, api):
        """PRD §3.2: "The `service_code` must be unique within the agency
        among services whose status is not `DEACTIVATED`; a collision is
        rejected with `ERR_DUPLICATE_SERVICE_CODE`."

        Design: Corner/errors/err_duplicate_service_code_reuse_after_deactivate
        """
        set_clock()
        agency = create_agency()
        service = create_service(agency["id"])  # DL-RENEW, DRAFT
        dup_payload = create_service_payload(
            agency["id"],
            name="Duplicate",
            fee_model="ABSORBED",
            allowed_methods=["CARD"],
            min_amount_cents=1,
            max_amount_cents=100,
            gl_code="9",
        )
        resp = api_client.create_service(dup_payload, AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_CODE)
        deactivate_service(service["id"])
        resp2 = api_client.create_service(
            dict(dup_payload, name="Replacement"), AA_LEAD
        )
        replacement = validate_success(resp2, 201)
        assert replacement["id"] != service["id"]


class TestStatutoryCoverageGate:
    def test_no_statutory_coverage_on_service_activate(self, api):
        """PRD §3.2: "A `CONVENIENCE_FEE` service additionally needs at least
        one statutory authorization of the service whose `in_effect` holds at
        the logical clock, otherwise `ERR_NO_STATUTORY_COVERAGE`; `ABSORBED`
        services need none."

        Design: Corner/errors/err_no_statutory_coverage_on_service_activate
        """
        built = setup_active_agency()
        agency_id = built["agency"]["id"]
        cf_service = create_service(agency_id, fee_model="CONVENIENCE_FEE")
        resp = api_client.activate_service(cf_service["id"], PA)
        validate_error(resp, ApiErrorId.ERR_NO_STATUTORY_COVERAGE)
        assert get_service(cf_service["id"])["status"] == "DRAFT"
        absorbed = create_service(
            agency_id,
            service_code="TAG-FEE",
            name="Tag Fee Absorbed",
            fee_model="ABSORBED",
            allowed_methods=["CARD"],
            min_amount_cents=100,
            max_amount_cents=100000,
            gl_code="4120",
        )
        activated = activate_service(absorbed["id"])
        assert activated["status"] == "ACTIVE", "statutory coverage is only a CONVENIENCE_FEE gate"


class TestAuthorizationWindowOverlap:
    def test_authorization_touching_window_approve_rejected(self, api):
        """PRD §3.2: "no other `APPROVED` authorization of the same service
        may have a closed window intersecting this one — since the intervals
        are closed, one authorization's `effective_from` landing exactly on
        another's `effective_to` is an overlap, rejected with
        `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/authorization_closed_interval_touching_is_overlap
        """
        ctx = setup_cf_checkout(with_payer=False)  # APPROVED window [2026-01-01, 2027-12-31]
        touching = create_authorization(
            ctx["service"]["id"],
            statute_citation="62 O.S. 34.9 (amended)",
            disclosure_text_version="D2",
            fee_cap_cents=6000,
            effective_from="2027-12-31T00:00:00Z",  # == the existing window's effective_to
            effective_to="2028-06-30T00:00:00Z",
        )
        resp = api_client.approve_statutory_authorization(touching["id"], PA)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)
        rows, _ = validate_paginated(
            api_client.list_statutory_authorizations(ctx["service"]["id"], PA)
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[touching["id"]]["status"] == "DRAFT"

    def test_authorization_next_day_window_approves(self, api):
        """PRD §3.2: "a closed effectiveness window running from
        `effective_from` through `effective_to`, both bounds inclusive."

        Design: Difficulty/resource_temporal_overlap/authorization_closed_interval_touching_is_overlap
        """
        ctx = setup_cf_checkout(with_payer=False)
        later = create_authorization(
            ctx["service"]["id"],
            statute_citation="62 O.S. 34.9 (amended)",
            disclosure_text_version="D2",
            fee_cap_cents=6000,
            effective_from="2028-01-01T00:00:00Z",  # strictly after the existing effective_to
            effective_to="2028-06-30T00:00:00Z",
        )
        resp = api_client.approve_statutory_authorization(later["id"], PA)
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"
