"""Registration, response envelope, not-found identifiers, and auth ladder.

Covers organization registration defaults, the uniform error envelope,
per-family 404s on path and body references, and the first two rungs of the
validation ladder.
"""
from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_carrier,
    assert_common_timestamp,
    create_carrier_payload,
    is_valid_uuid,
    make_carrier_rep_headers,
    make_ombuds_officer_headers,
    make_shipper_rep_headers,
    set_logical_clock,
    setup_carrier_shipper,
    setup_published_tariff,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DOCKET = TEST_USERS["docket_headers"]


class TestRegistrationAndEnvelope:
    def test_carrier_create_returns_declared_fields_and_system_defaults(self):
        """PRD §3.1: "A new organization begins in `ACTIVE` status with a
        `compliance_score` of 1000 and `cumulative_civil_penalties_cents` of zero".
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/carrier_create_returns_declared_fields_and_system_defaults
        """
        set_logical_clock()
        resp = api_client.create_carrier(
            create_carrier_payload(org_name="Corner Carriers", org_type="VOCC"), ADMIN)
        body = resp.json()
        data = validate_success(resp, 201)
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert_common_timestamp(body["meta"]["api_request_timestamp"],
                                "meta.api_request_timestamp")
        assert_carrier(data)
        assert data["status"] == "ACTIVE"
        assert data["compliance_score"] == 1000
        assert data["cumulative_civil_penalties_cents"] == 0
        assert is_valid_uuid(data["id"])
        # Presence/type only for version: the PRD pins that it "starts at
        # creation and increments by one on every mutation" without fixing
        # the initial literal.
        assert isinstance(data["version"], int)

    def test_carrier_org_type_invalid_enum_returns_invalid_request(self):
        """PRD §3.1: "an `org_type` — one of `VOCC` (vessel-operating common
        carrier), `MTO` (marine terminal operator), `NVOCC` (non-vessel-operating
        common carrier), or `OFF` (ocean freight forwarder)".
        PRD §2.7: "Request shape and scalar sanity — required fields present,
        enumerations valid, dates coherent, numerics in range (`ERR_INVALID_REQUEST`,
        `ERR_INVOICE_MISSING_REQUIRED_ELEMENT`, `ERR_INVALID_INVOICE_DATES`)."

        Design: Corner/entities/carrier_org_type_invalid_enum_returns_invalid_request
        """
        set_logical_clock()
        resp = api_client.create_carrier(
            {"org_name": "Bogus Brokerage", "org_type": "BROKER"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Nothing was registered.
        validate_error(api_client.get_carrier(MISSING_UUID, DOCKET),
                       ApiErrorId.ERR_CARRIER_NOT_FOUND)

    def test_error_envelope_shape_is_uniform(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `message` provides
        a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_is_uniform
        """
        set_logical_clock()
        resp = api_client.get_carrier(MISSING_UUID, DOCKET)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        error = validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)
        assert error["error_id"] == "ERR_CARRIER_NOT_FOUND"
        assert isinstance(error["message"], str) and error["message"].strip()
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_unknown_path_ids_return_entity_specific_404s(self):
        """PRD §2.8: "Each resource family has its own not-found identifier, all
        HTTP 404: `ERR_CARRIER_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`,
        `ERR_TARIFF_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_LICENSE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, and `ERR_PROCEEDING_NOT_FOUND`."

        Design: Corner/entities/unknown_path_ids_return_entity_specific_404s
        """
        set_logical_clock()
        cases = [
            (api_client.get_carrier(MISSING_UUID, DOCKET),
             ApiErrorId.ERR_CARRIER_NOT_FOUND),
            (api_client.get_agreement(MISSING_UUID, DOCKET),
             ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api_client.get_invoice(MISSING_UUID, DOCKET),
             ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (api_client.get_complaint(MISSING_UUID, DOCKET),
             ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
            (api_client.get_proceeding(MISSING_UUID, DOCKET),
             ApiErrorId.ERR_PROCEEDING_NOT_FOUND),
        ]
        for resp, err_id in cases:
            assert resp.status_code == 404
            validate_error(resp, err_id)

    def test_unknown_body_reference_ids_return_entity_specific_404s(self):
        """PRD §2.8: "The same per-family errors report body references that fail
        to resolve — a `shipper_id`, a `tariff_id`, a `service_contract_id`, a
        `billed_party_shipper_id`, a `respondent_carrier_id`, an element of
        `subject_invoice_ids`, or an element of `member_carrier_ids` that names
        nothing."

        Design: Corner/entities/unknown_body_reference_ids_return_entity_specific_404s
        """
        env = setup_published_tariff()
        set_logical_clock("2026-09-10T00:00:00Z")
        carrier = env["carrier"]
        shipper = env["shipper"]
        tariff = env["tariff"]
        rep = make_carrier_rep_headers(carrier["id"])

        base_invoice = {
            "billed_party_shipper_id": shipper["id"],
            "container_number": "MSKU9000011",
            "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-08T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z",
        }
        r1 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-NF-1", "charge_basis": "TARIFF",
            "tariff_id": MISSING_UUID, **base_invoice}, rep)
        validate_error(r1, ApiErrorId.ERR_TARIFF_NOT_FOUND)

        r2 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-NF-2", "charge_basis": "TARIFF",
            "tariff_id": tariff["id"], **base_invoice,
            "billed_party_shipper_id": MISSING_UUID}, rep)
        validate_error(r2, ApiErrorId.ERR_SHIPPER_NOT_FOUND)

        r3 = api_client.create_invoice(carrier["id"], {
            "invoice_number": "INV-NF-3", "charge_basis": "SERVICE_CONTRACT",
            "service_contract_id": MISSING_UUID, **base_invoice}, rep)
        validate_error(r3, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

        r4 = api_client.append_surety_bond(MISSING_UUID, {
            "bond_ref": "B1", "surety_name": "Pacific Surety",
            "coverage_cents": 7_500_000}, rep)
        validate_error(r4, ApiErrorId.ERR_LICENSE_NOT_FOUND)

        r5 = api_client.respond_to_dispute(MISSING_UUID, {"resolution": "WAIVE"}, rep)
        validate_error(r5, ApiErrorId.ERR_DISPUTE_NOT_FOUND)

        rows, _meta = validate_paginated(
            api_client.list_invoices(DOCKET, params={"carrier_id": carrier["id"]}))
        assert rows == [], "no invoice may persist from rejected references"


class TestAuthLadder:
    def test_missing_auth_headers_beat_all_other_failures(self):
        """PRD §2.7: "Every request walks an ordered ladder of checks, and
        evaluation stops at the first failure" beginning with "1. Header presence
        and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."
        PRD §2.1: "A request missing either header, or whose `X-User-Role` names
        no declared role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_beat_all_other_failures
        """
        set_logical_clock()
        r1 = api_client.create_complaint({
            "respondent_carrier_id": MISSING_UUID,
            "subject_invoice_ids": [],
            "reparations_claimed_cents": 50_000,
        }, None)
        validate_error(r1, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        r2 = api_client.get_carrier(MISSING_UUID, None)
        validate_error(r2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_denials_return_insufficient_permissions(self):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.7: "2. Role authorization for the endpoint
        (`ERR_INSUFFICIENT_PERMISSIONS`)." precedes "4. Path identifier existence".

        Design: Corner/rbac/role_denials_return_insufficient_permissions
        """
        env = setup_carrier_shipper()
        r1 = api_client.create_carrier(
            {"org_name": "Shipper Pretending", "org_type": "VOCC"},
            make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(r1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        r2 = api_client.determine_proceeding(MISSING_UUID, {
            "determination": "VIOLATION_FOUND", "violation_count": 1,
            "willful": False}, make_carrier_rep_headers(MISSING_UUID))
        validate_error(r2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        r3 = api_client.refer_ombuds(MISSING_UUID, {"ombuds_officer_id": "om-x"},
                                     make_ombuds_officer_headers("om-x"))
        validate_error(r3, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
