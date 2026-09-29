"""The error surface itself: entity-specific 404s and the shared error envelope.

Two properties are checked here that no single business test can establish on its
own — that nine different resource paths report nine different existence errors,
and that structurally different failures still return the identical envelope.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import (
    ADMIN_1,
    ANALYST_1,
    BILLING_1,
    COUNSELOR_1,
    HRA_ADMIN_1,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
)


def test_every_resource_path_reports_its_own_not_found_error(api):
    """One absent id, nine paths, nine distinct error ids.

    PRD 2.8 gives each entity its own existence rung and its own identifier:
    rung 3 "A `plan_year_id` in the path or body resolves to an existing plan
    year → `ERR_PLAN_YEAR_NOT_FOUND` (404)", rung 4 "A `retiree_id` in the path
    or body resolves to an existing retiree → `ERR_RETIREE_NOT_FOUND` (404)",
    rung 6 "A `determination_id` in the path resolves to an existing eligibility
    determination → `ERR_DETERMINATION_NOT_FOUND` (404), on every determination
    read and write.", rung 7 "An `election_event_id` in the path resolves to an
    existing election event → `ERR_ELECTION_EVENT_NOT_FOUND` (404), on every
    election-event read and write.", rung 8 "An `enrollment_id` in the path or
    body resolves to an existing enrollment → `ERR_ENROLLMENT_NOT_FOUND` (404)",
    rung 10 "A `claim_id` in the path resolves to an existing reimbursement claim
    → `ERR_CLAIM_NOT_FOUND` (404), on every claim read and write." and rung 11
    "An `invoice_id` in the path resolves to an existing premium invoice →
    `ERR_INVOICE_NOT_FOUND` (404), on every invoice read and write." Because
    PRD 2.2 says "The `error_id` is a unique, machine-readable string that
    identifies the specific error.", one shared generic identifier will not do.

    Design: Corner/errors/unknown_identifier_on_every_resource_path_not_found
    """
    admin = make_benefits_admin_headers(ADMIN_1)
    analyst = make_eligibility_analyst_headers(ANALYST_1)
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)
    hra_admin = make_hra_administrator_headers(HRA_ADMIN_1)
    billing = make_billing_clerk_headers(BILLING_1)

    probes = (
        (api.get_plan_year(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_PLAN_YEAR_NOT_FOUND),
        (api.get_retiree(NON_EXISTENT_UUID, analyst), ApiErrorId.ERR_RETIREE_NOT_FOUND),
        (
            api.get_plan_option(NON_EXISTENT_UUID, admin),
            ApiErrorId.ERR_PLAN_OPTION_NOT_FOUND,
        ),
        (
            api.get_determination(NON_EXISTENT_UUID, analyst),
            ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
        ),
        (
            api.get_election_event(NON_EXISTENT_UUID, counselor),
            ApiErrorId.ERR_ELECTION_EVENT_NOT_FOUND,
        ),
        (
            api.get_enrollment(NON_EXISTENT_UUID, counselor),
            ApiErrorId.ERR_ENROLLMENT_NOT_FOUND,
        ),
        (
            api.get_hra_account(NON_EXISTENT_UUID, hra_admin),
            ApiErrorId.ERR_HRA_ACCOUNT_NOT_FOUND,
        ),
        (api.get_claim(NON_EXISTENT_UUID, hra_admin), ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_invoice(NON_EXISTENT_UUID, billing), ApiErrorId.ERR_INVOICE_NOT_FOUND),
    )

    seen = []
    for response, expected in probes:
        error = validate_error(response, expected.value, expected_status=404)
        seen.append(error["error_id"])

    assert len(set(seen)) == 9


def test_a_shape_failure_and_an_existence_failure_share_one_envelope(api):
    """Different status codes, different ids, identical structure.

    PRD 2.2 fixes the error envelope: "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`.", "The `error_id`
    is a unique, machine-readable string that identifies the specific error." and
    "The `message` provides a human-readable explanation of what went wrong." The
    identifier and the timestamp keep the properties the success envelope
    declares — "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`." and "The `api_request_timestamp` is a
    server-generated ISO 8601 UTC timestamp with three fractional digits." — so
    two successive requests cannot share an id. The two failures come from
    PRD 2.8 rung 12, "every required body field is present", and rung 4.

    Design: Corner/errors/error_envelope_carries_meta_and_response_type_on_invalid_request
    """
    analyst = make_eligibility_analyst_headers(ANALYST_1)

    shape = api.create_retiree({"full_name": "No Dates Given"}, analyst)
    validate_error(shape, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    missing = api.get_retiree(NON_EXISTENT_UUID, analyst)
    validate_error(missing, ApiErrorId.ERR_RETIREE_NOT_FOUND.value, expected_status=404)

    bodies = [shape.json(), missing.json()]
    for body in bodies:
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert set(body["data"]) == {"error_id", "message"}
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        for leaked in ("id", "version", "created_at", "updated_at", "full_name"):
            assert leaked not in body["data"]

    assert bodies[0]["meta"]["api_request_id"] != bodies[1]["meta"]["api_request_id"]
    assert bodies[0]["data"]["error_id"] != bodies[1]["data"]["error_id"]

    _rows, meta = validate_paginated(api.list_retirees(analyst))
    assert meta["total_count"] == 0
