"""RBAC and request-context enforcement: header presence and role vocabulary
(priority 1), per-endpoint role admission (priority 2), and the entity-backed
Client ownership chain (priority 4)."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    TEST_USERS,
    create_client,
    create_intake_request,
    create_intake_request_payload,
    create_jurisdiction,
    create_policy_initiative_payload,
    get_case,
    get_intake_request,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    log_contact_payload,
    make_client_headers,
    setup_accepted_case,
    setup_intake_pipeline,
    validate_created,
    validate_error,
    validate_ok,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SPECIALIST = TEST_USERS["intake_specialist_headers"]
ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]


def test_any_endpoint_missing_auth_headers_rejected(api):
    """PRD section 2.1: "Every request must carry `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user
    acts. A request in which either header is missing or empty, or whose
    `X-User-Role` value is not one of the declared role names, is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/any_endpoint_missing_auth_headers_rejected
    """
    jurisdiction = create_jurisdiction(state_code="SD", name="South Dakota")

    # No credentials at all — even on a read-only GET of an existing resource.
    validate_error(
        api.get_jurisdiction(jurisdiction["id"], {}),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    )
    # Each missing-or-empty variant is the same priority-1 rejection.
    for bad_headers in (
        headers_without_user_id(),
        headers_without_role(),
        headers_with_empty_user_id(),
    ):
        validate_error(
            api.get_jurisdiction(jurisdiction["id"], bad_headers),
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )


def test_request_with_invalid_role_header_rejected(api):
    """PRD section 2.1: "A request in which either header is missing or empty,
    or whose `X-User-Role` value is not one of the declared role names, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD section 2.1: "The system recognizes exactly eight roles:
    `PlatformAdmin`, `IntakeSpecialist`, `ManagingAttorney`, `StaffAttorney`,
    `EvidenceAnalyst`, `ClientServicesAdvocate`, `PolicyDirector`, and
    `Client`."

    Design: Corner/validations/request_with_invalid_role_header_rejected
    """
    jurisdiction = create_jurisdiction(state_code="WY", name="Wyoming")
    # A syntactically present but undeclared role name fails header validity
    # (priority 1), not role authorization (which would be a 403).
    validate_error(
        api.get_jurisdiction(jurisdiction["id"], headers_with_undeclared_role()),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    )


def test_evidence_analyst_cannot_create_petition(api):
    """PRD section 2.1: "Each endpoint admits a fixed set of roles (§4); a
    request whose role is well-formed but not admitted by the addressed
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: POST `/legal-petitions` admits StaffAttorney only.

    Design: Corner/validations/evidence_analyst_cannot_create_petition
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "OK", "name": "Oklahoma"}
    )
    resp = api.create_legal_petition(
        {
            "case_id": ctx["case"]["id"],
            "petition_type": "DIRECT_APPEAL",
            "court_name": "OK Court of Criminal Appeals",
            "claim_basis": "PROCEDURAL",
        },
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_client_reading_another_clients_case_rejected(api):
    """PRD section 2.1: "a `Client` may read its own `Client` record, may read
    an intake request only when the request's `client_id` equals `X-User-ID`,
    may read a case only when the case's `intake_request_id` leads to an
    intake request whose `client_id` equals `X-User-ID`".
    PRD section 2.1: "Any `Client`-role call that fails one of these ownership
    checks is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/client_reading_another_clients_case_rejected
    """
    jurisdiction = create_jurisdiction(state_code="HI", name="Hawaii")
    owner = create_client(full_name="Client Alpha", inmate_number="HI-A")
    stranger = create_client(full_name="Client Beta", inmate_number="HI-B")
    ctx = setup_accepted_case(
        jurisdiction_id=jurisdiction["id"], client_id=owner["id"]
    )

    validate_error(
        api.get_case(ctx["case"]["id"], make_client_headers(stranger["id"])),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
    )
    data = validate_ok(api.get_case(ctx["case"]["id"], make_client_headers(owner["id"])))
    assert data["status"] == "OPEN"
    assert data["id"] == ctx["case"]["id"]


def test_client_cannot_decide_intake(api):
    """PRD section 4: POST `/intake-requests/{id}/decide` admits
    ManagingAttorney only.
    PRD section 2.1: "a request whose role is well-formed but not admitted by
    the addressed endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/client_cannot_decide_intake
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "VT", "name": "Vermont"},
        recommendation="ACCEPT",
    )
    resp = api.decide_intake_request(
        ctx["intake"]["id"],
        {"decision": "ACCEPTED"},
        make_client_headers(ctx["client"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_intake_request(ctx["intake"]["id"])["status"] == "DECISION_PENDING"


def test_policy_initiative_create_requires_policy_director(api):
    """PRD section 4: POST `/policy-initiatives` admits PolicyDirector only.
    PRD section 2.1: "a request whose role is well-formed but not admitted by
    the addressed endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/policy_initiative_create_requires_policy_director
    """
    jurisdiction = create_jurisdiction(state_code="NM", name="New Mexico")
    resp = api.create_policy_initiative(
        create_policy_initiative_payload(
            jurisdiction["id"],
            topic="DATABASE_ACCESS",
            title="Widen offender-db comparison rights",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_clock_set_requires_platform_admin(api):
    """PRD section 4: POST `/_clock/set_current_utc` admits PlatformAdmin only.
    PRD section 2.4: "Before any clock-setting call has been made, the logical
    clock reads exactly `2026-09-01T00:00:00Z`; the server must not silently
    fall back to the host's wall clock under any circumstance."
    PRD section 2.1: "a request whose role is well-formed but not admitted by
    the addressed endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/clock_set_requires_platform_admin
    """
    resp = api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    # The rejected call moved nothing: business timestamps still read the
    # default logical clock. PRD section 3.1: a new case opens with
    # "`last_contact_at` set to the current logical clock", and section 2.4
    # pins that clock to exactly CLOCK_DEFAULT before any successful set.
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "WY", "name": "Wyoming"}
    )
    assert ctx["case"]["last_contact_at"] == CLOCK_DEFAULT


def test_intake_specialist_cannot_log_contact(api):
    """PRD section 4: POST `/cases/{id}/log-contact` admits
    ClientServicesAdvocate only.
    PRD section 2.1: "a request whose role is well-formed but not admitted by
    the addressed endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/intake_specialist_cannot_log_contact
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "IA", "name": "Iowa"}
    )
    resp = api.log_case_contact(
        ctx["case"]["id"],
        log_contact_payload(channel="PHONE", expectation_setting="NEUTRAL"),
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_case(ctx["case"]["id"])["contact_count"] == 0


def test_client_self_submission_and_owned_reads_work(api):
    """PRD section 2.1: "a `Client` self-submitting an intake request must
    supply a `client_id` equal to `X-User-ID`."
    PRD section 3.1: "An `IntakeSpecialist` may create the request on a
    client's behalf; a `Client` may self-submit, in which case the payload's
    `client_id` must equal the caller's `X-User-ID` or the create is rejected
    with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/client_self_submission_and_owned_reads_work
    """
    jurisdiction = create_jurisdiction(state_code="UT", name="Utah")
    owner = create_client(full_name="Self Submitter", inmate_number="UT-31")
    other = create_client(full_name="Other Person", inmate_number="UT-32")

    # Self-submission naming ANOTHER client_id is an ownership violation.
    resp = api.create_intake_request(
        create_intake_request_payload(
            other["id"], jurisdiction["id"], conviction_summary="Forged submission"
        ),
        make_client_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    # Self-submission with the caller's own id succeeds.
    data = validate_created(
        api.create_intake_request(
            create_intake_request_payload(
                owner["id"], jurisdiction["id"], conviction_summary="Own submission"
            ),
            make_client_headers(owner["id"]),
        )
    )
    assert data["status"] == "RECEIVED"
    assert data["client_id"] == owner["id"]

    # The owner reads its own intake request.
    fetched = validate_ok(
        api.get_intake_request(data["id"], make_client_headers(owner["id"]))
    )
    assert fetched["id"] == data["id"]
