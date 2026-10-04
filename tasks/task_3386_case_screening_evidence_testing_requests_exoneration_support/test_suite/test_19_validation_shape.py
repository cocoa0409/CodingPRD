"""Request-shape and existence validation: unknown references, closed enum
vocabularies, required fields, format constraints, uniqueness, unknown
advance events, unknown payload fields, and per-resource 404 codes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_case,
    create_client,
    create_client_payload,
    create_evidence_item_payload,
    create_intake_request_payload,
    create_jurisdiction,
    create_jurisdiction_payload,
    setup_accepted_case,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SPECIALIST = TEST_USERS["intake_specialist_headers"]
ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]
ADVOCATE = TEST_USERS["client_services_advocate_headers"]
POLICY = TEST_USERS["policy_director_headers"]


def test_create_with_unknown_case_reference_returns_not_found(api):
    """PRD section 2.9 item 3: "Resource identifiers must resolve. Path
    identifiers are validated first, strictly left-to-right; identifiers
    referenced in the request body (`client_id`, `jurisdiction_id`,
    `case_id`, `evidence_item_id`, `authorization_id`, `provider_id`) are then
    validated in payload field order. The first unresolved reference produces
    the corresponding not-found error".

    Design: Corner/validations/create_with_unknown_case_reference_returns_not_found
    """
    resp = api.create_evidence_item(
        create_evidence_item_payload(
            "99999999-8888-4777-8666-555555555555",
            description="Orphan",
            evidence_type="OTHER",
            custodian_type="COURT_CLERK",
            initial_sample_ng=5,
        ),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


def test_intake_create_with_invalid_enum_rejected(api):
    """PRD section 2.9 item 6: "Required fields must be present, types must be
    correct, enum values must be in vocabulary".
    PRD section 2.9 item 6: "unknown fields are rejected, a lab window's
    `scheduled_end` must be strictly after its `scheduled_start`, and a
    service window's `service_end` must be strictly after its
    `service_start` — any violation is `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD section 3.1: "the `claim_strength` on the scale `WEAK`, `MODERATE`,
    `STRONG`, `COMPELLING`".

    Design: Corner/validations/intake_create_with_invalid_enum_rejected
    """
    jurisdiction = create_jurisdiction(state_code="AL", name="Alabama")
    client = create_client(full_name="Eli Vann", inmate_number="AL-3")
    resp = api.create_intake_request(
        create_intake_request_payload(
            client["id"], jurisdiction["id"], claim_strength="OVERWHELMING"
        ),
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_intake_create_missing_required_field_rejected(api):
    """PRD section 2.9 item 6: "Required fields must be present, types must be
    correct, enum values must be in vocabulary".

    Design: Corner/validations/intake_create_missing_required_field_rejected
    """
    jurisdiction = create_jurisdiction(state_code="AK", name="Alaska")
    client = create_client(full_name="Mel Tarr", inmate_number="AK-4")
    payload = create_intake_request_payload(client["id"], jurisdiction["id"])
    del payload["claim_strength"]
    resp = api.create_intake_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_jurisdiction_create_with_malformed_state_code_rejected(api):
    """PRD section 2.8: "A jurisdiction is identified by its `state_code` — a
    unique two-letter uppercase code".
    PRD section 2.9 item 6: "Required fields must be present, types must be
    correct, enum values must be in vocabulary".

    Design: Corner/validations/jurisdiction_create_with_malformed_state_code_rejected
    """
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(state_code="Texas", name="Texas"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_jurisdiction_duplicate_state_code_rejected(api):
    """PRD section 2.8: "A jurisdiction is identified by its `state_code` — a
    unique two-letter uppercase code; a duplicate registration is rejected
    with `ERR_DUPLICATE_STATE_CODE` (HTTP 409)".

    Design: Corner/validations/jurisdiction_duplicate_state_code_rejected
    """
    create_jurisdiction(state_code="TX", name="Texas")
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(
            state_code="TX",
            name="Texas (duplicate)",
            has_post_conviction_dna_statute=False,
            clemency_available=False,
            compensation_statute_exists=False,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_CODE)


def test_case_advance_with_unknown_event_rejected(api):
    """PRD section 2.9 item 7: "On advance-style endpoints, the payload's
    `event` must belong to the endpoint's declared vocabulary — else
    `ERR_INVALID_TRANSITION_EVENT` (HTTP 400)."

    Design: Corner/validations/case_advance_with_unknown_event_rejected
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "MN", "name": "Minnesota"}
    )
    assert ctx["case"]["status"] == "OPEN"
    resp = api.advance_case(ctx["case"]["id"], {"event": "FLY"}, ATTORNEY)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION_EVENT)


def test_client_create_with_extra_field_rejected(api):
    """PRD section 2.9 item 6: "unknown fields are rejected, a lab window's
    `scheduled_end` must be strictly after its `scheduled_start`, and a
    service window's `service_end` must be strictly after its
    `service_start` — any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/client_create_with_extra_field_rejected
    """
    payload = create_client_payload(full_name="Rey Sol", inmate_number="ZZ-1")
    payload["nickname"] = "Speedy"
    resp = api.create_client(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_case_with_unknown_id_returns_not_found(api):
    """PRD section 2.9: "The first unresolved reference produces the
    corresponding not-found error: `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_INTAKE_REQUEST_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, ... each HTTP 404."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/get_case_with_unknown_id_returns_not_found
    """
    resp = api.get_case("11111111-2222-4333-8444-555555555555", ATTORNEY)
    data = validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)
    assert data["message"], "the error envelope carries a human-readable message"


def test_every_resource_address_404s_with_its_specific_code(api):
    """PRD section 2.9: "3. Existence. Resource identifiers must resolve. Path
    identifiers are validated first, strictly left-to-right ... The first
    unresolved reference produces the corresponding not-found error:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`,
    `ERR_INTAKE_REQUEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`,
    `ERR_TESTING_AUTHORIZATION_NOT_FOUND`, `ERR_LAB_ANALYSIS_NOT_FOUND`,
    `ERR_LEGAL_PETITION_NOT_FOUND`, `ERR_COMPENSATION_CLAIM_NOT_FOUND`,
    `ERR_REENTRY_PROVIDER_NOT_FOUND`, `ERR_REENTRY_REFERRAL_NOT_FOUND`, or
    `ERR_POLICY_INITIATIVE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_resource_address_404s_with_its_specific_code
    """
    probes = [
        (api.get_jurisdiction("11111111-1111-4111-8111-111111111111", ADMIN),
         ApiErrorId.ERR_JURISDICTION_NOT_FOUND),
        (api.get_client("22222222-2222-4222-8222-222222222222", SPECIALIST),
         ApiErrorId.ERR_CLIENT_NOT_FOUND),
        (api.get_intake_request("33333333-3333-4333-8333-333333333333", SPECIALIST),
         ApiErrorId.ERR_INTAKE_REQUEST_NOT_FOUND),
        (api.get_case("99999999-9999-4999-8999-999999999999", ATTORNEY),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.advance_evidence_item(
            "44444444-4444-4444-8444-444444444444", {"event": "START_SEARCH"}, ANALYST),
         ApiErrorId.ERR_EVIDENCE_ITEM_NOT_FOUND),
        (api.advance_records_request(
            "55555555-5555-4555-8555-555555555555", {"event": "SUBMIT"}, ANALYST),
         ApiErrorId.ERR_RECORDS_REQUEST_NOT_FOUND),
        (api.get_testing_authorization(
            "66666666-6666-4666-8666-666666666666", ATTORNEY),
         ApiErrorId.ERR_TESTING_AUTHORIZATION_NOT_FOUND),
        (api.advance_lab_analysis(
            "77777777-7777-4777-8777-777777777777", {"event": "CANCEL"}, ATTORNEY),
         ApiErrorId.ERR_LAB_ANALYSIS_NOT_FOUND),
        (api.advance_legal_petition(
            "88888888-8888-4888-8888-888888888888", {"event": "APPEAL"}, ATTORNEY),
         ApiErrorId.ERR_LEGAL_PETITION_NOT_FOUND),
        (api.advance_compensation_claim(
            "99999999-9999-4999-8999-999999999999", {"event": "APPEAL"}, ATTORNEY),
         ApiErrorId.ERR_COMPENSATION_CLAIM_NOT_FOUND),
        (api.get_reentry_provider("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ADVOCATE),
         ApiErrorId.ERR_REENTRY_PROVIDER_NOT_FOUND),
        (api.advance_reentry_referral(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", {"event": "CANCEL"}, ADVOCATE),
         ApiErrorId.ERR_REENTRY_REFERRAL_NOT_FOUND),
        (api.advance_policy_initiative(
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc", {"event": "STALL"}, POLICY),
         ApiErrorId.ERR_POLICY_INITIATIVE_NOT_FOUND),
    ]
    for response, expected in probes:
        data = validate_error(response, expected)
        assert data["message"]
