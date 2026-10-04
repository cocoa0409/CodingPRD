"""The single door: client registration, assessments and reviewer return."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_funder, create_program, create_grant, open_assessment,
    open_screen, verify_screen, submit_assessment, walk_screen_to_routed,
    refresh_screen, make_client_headers, ApiErrorId, NON_EXISTENT_UUID,
    INTAKE, COMPLIANCE,
)


def test_client_create_applies_confidentiality_and_consent_defaults():
    """PRD §3.2: "`confidentiality_tier` defaults to `STANDARD` and may be
    raised to `PROTECTED` or `SEALED`; `consent_scope` defaults to an empty list".
    PRD §3.2: "A newly registered client starts with an `open_enrollment_count`
    of 0."
    PRD §2.4: "The `created_at` property records when the row was first written,
    as an ISO 8601 UTC timestamp with exactly three fractional digits".

    Design: Corner/entities/client_create_applies_confidentiality_and_consent_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_client(
        {
            "full_name": "Ada Vance",
            "date_of_birth": "1990-01-01",
            "household_size": 2,
            "immigration_status": "CITIZEN",
            "county_code": "COOK",
        },
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["confidentiality_tier"] == "STANDARD", "the tier defaults to STANDARD"
    assert data["consent_scope"] == [], "consent_scope defaults to an empty list"
    assert data["open_enrollment_count"] == 0, "a new client starts at 0 open enrollments"
    assert data["created_at"] == "2026-09-01T00:00:00.000Z"
    assert data["version"] >= 1


def test_client_get_unknown_id_returns_not_found_error_envelope():
    """PRD §3.2: "If the named client cannot be resolved on a later read, the
    answer is `ERR_CLIENT_NOT_FOUND`."
    PRD §2.10: "The specific codes are `ERR_CLIENT_NOT_FOUND` (HTTP 404) when a
    client path segment does not resolve".

    Design: Corner/entities/client_get_unknown_id_returns_not_found_error_envelope
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_client(NON_EXISTENT_UUID, INTAKE)
    error = validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND)
    assert error["error_id"] == "ERR_CLIENT_NOT_FOUND"


def test_intake_assessment_path_client_must_resolve_before_body_is_read():
    """PRD §2.11: "A request that opens an intake assessment beneath a client
    path segment resolves that segment against the `Client` collection first;
    if no client carries that identifier, the answer is `ERR_CLIENT_NOT_FOUND`
    and the assessment is never considered."

    Design: Corner/entities/intake_assessment_path_client_must_resolve_before_body_is_read
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_intake_assessment(
        NON_EXISTENT_UUID,
        {
            "assessment_date": "2026-09-01T00:00:00Z",
            "presenting_needs": ["rent arrears"],
            "requested_domains": ["HOUSING"],
        },
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND)


def test_client_role_reads_own_record_through_entity_backed_identity():
    """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the
    acting `Client`; ownership checks on any resource that references a `Client`
    compare the resource's foreign-key field to `X-User-ID`, so a client may
    read only their own record."

    Design: Corner/validations/client_role_reads_own_record_through_entity_backed_identity
    """
    set_clock("2026-09-01T00:00:00Z")
    client = create_client(full_name="Ada Vance")
    resp = api_client.get_client(client["id"], make_client_headers(client["id"]))
    data = validate_success(resp)
    assert data["id"] == client["id"]
    assert data["full_name"] == "Ada Vance"
    assert data["confidentiality_tier"] == "STANDARD"


def test_intake_submit_from_routed_returns_invalid_state_without_side_effects():
    """PRD §3.3: "Submission moves the assessment from `DRAFT` to `SUBMITTED`,
    and it is also the path back from `RETURNED` to `SUBMITTED`."
    PRD §3.3: "An operation attempted against an assessment whose status is not
    the from-state of any transition that operation may trigger — including any
    attempt to act on a closed assessment — is refused with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/intake_submit_from_routed_returns_invalid_state_without_side_effects
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client()
    walked = walk_screen_to_routed(client["id"], program["id"], grant["id"])
    assessment = walked["assessment"]

    before = get_success_data(api_client.get_intake_assessment(assessment["id"], INTAKE))
    assert before["status"] == "ROUTED"

    resp = api_client.submit_intake_assessment(assessment["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api_client.get_intake_assessment(assessment["id"], INTAKE))
    assert after["status"] == "ROUTED", "the refused call leaves the status untouched"
    assert after["version"] == before["version"], "the refused call leaves the version untouched"


def test_intake_return_expires_every_screen_verification():
    """PRD §3.3: "Returning an assessment is not a local edit. It sets the
    assessment to `RETURNED`, expires the evidence gathered so far by setting
    every eligibility screen under the assessment to `verification_state` of
    `EXPIRED`, and resets every screen that had been determined `ELIGIBLE` back
    to `determination` of `PENDING`."
    PRD §3.3: "The assessment's `version` is incremented, and so is the
    `version` of every screen the return touched."

    Design: Corner/state_machines/intake_return_expires_every_screen_verification
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    grant = create_grant(funder["id"], program["id"], grant_code="G-1")
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], program["id"], grant["id"])
    verified = verify_screen(screen["id"])
    submit_assessment(assessment["id"])

    resp = api_client.return_intake_assessment(
        assessment["id"], {"return_reason_code": "MISSING_DOCUMENT"}, COMPLIANCE
    )
    data = validate_success(resp)
    assert data["status"] == "RETURNED"
    assert data["return_reason_code"] == "MISSING_DOCUMENT"

    after = refresh_screen(screen["id"])
    assert after["verification_state"] == "EXPIRED", "the return expires the gathered evidence"
    assert after["determination"] == "PENDING", "expiry does not touch the determination dimension"
    assert after["version"] == verified["version"] + 1, "every screen the return touched is bumped"
