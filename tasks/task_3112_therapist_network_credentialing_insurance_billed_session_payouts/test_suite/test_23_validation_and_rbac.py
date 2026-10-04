"""Authentication, authorization and the referential/fiscal gates."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    create_malpractice_policy_payload,
    credential_clinician,
    get_clinician,
    get_enrollment,
    make_clinician,
    make_enrollment,
    make_license,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_patient_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PAYROLL = TEST_USERS["payroll_service_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000009"


def test_a_request_missing_the_role_header_is_unauthenticated_before_any_lookup_runs():
    """PRD §2.1: "A request that omits either header, supplies an empty
    `X-User-ID`, or names a role outside the declared set is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.9: "The sequence is: authentication first, so a missing header surfaces
    as `ERR_UNAUTHENTICATED` rather than being masked by any later check."

    Design: Corner/validations/missing_role_header_returns_unauthenticated_before_any_lookup
    """
    set_clock(CLOCK_EARLY)
    response = api_client.get_clinician(NON_EXISTENT, MISSING_ROLE_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_CLINICIAN_NOT_FOUND.value

    blank_id = api_client.get_clinician(NON_EXISTENT, MISSING_USER_ID_HEADERS)
    validate_error(blank_id, ApiErrorId.ERR_UNAUTHENTICATED)
    assert blank_id.status_code == 401


def test_a_role_outside_the_declared_set_is_rejected_at_authentication_not_authorization():
    """PRD §2.1: "The system recognises exactly six roles: `OpsAdmin`,
    `ComplianceOfficer`, `Clinician`, `Patient`, `PayrollService` and
    `Anonymous`."

    Design: Corner/validations/undeclared_role_is_rejected_at_authentication
    """
    set_clock(CLOCK_EARLY)
    response = api_client.create_clinician(
        {
            "full_name": "Avery Lin",
            "license_type": "LCSW",
            "primary_state": "CA",
            "specialty_tags": ["ANXIETY"],
            "weekly_caseload_target": 5,
            "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
        },
        UNDECLARED_ROLE_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
    assert api_client.list_clinicians(OPS).json()["data"] == []


def test_a_clinician_cannot_patch_a_payer_because_payer_administration_is_ops_admin_only():
    """PRD §2.1: "Where a role is not listed as authorised for an endpoint, the
    attempt fails with `ERR_UNAUTHORIZED`."
    PRD §2.1: "`OpsAdmin` is the network operator: it onboards clinicians,
    records licenses and malpractice policies, publishes payers and rate
    schedules"

    Design: Corner/validations/clinician_cannot_patch_a_payer_because_the_operation_is_ops_admin_exclusive
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()

    response = api_client.patch_payer(
        payer["id"], {"status": "SUSPENDED_AT_PAYER"}, make_clinician_headers(clinician["id"])
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value
    assert validate_success(api_client.get_payer(payer["id"], OPS))["status"] == "ACTIVE"
    assert api_client.list_payer_enrollments_for_payer(payer["id"], OPS).json()["data"] == []


def test_a_license_addressed_under_the_wrong_clinician_fails_as_a_missing_license():
    """PRD §2.8: "The system confirms the existence of the leftmost resource first,
    then the next, and only then any body-supplied identifiers, which are
    themselves checked in the declared input order of the endpoint."
    PRD §2.8: "The first identifier that does not resolve ends the request"

    Design: Corner/validations/compliance_officer_cannot_verify_another_clinicians_scope_through_a_mismatched_path
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(clinician["id"])
    other = make_clinician(
        full_name="Rafael Duarte",
        license_type="LMFT",
        specialty_tags=["TRAUMA"],
        weekly_caseload_target=6,
        availability_blocks=[{"weekday": 5, "start_minute": 480, "end_minute": 1080}],
    )

    response = api_client.verify_license(other["id"], license_row["id"], COMPLIANCE)
    error = validate_error(response, ApiErrorId.ERR_LICENSE_NOT_FOUND)
    assert response.status_code == 404
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    rows = api_client.list_licenses(clinician["id"], OPS).json()["data"]
    assert rows[0]["verification_status"] == "UNVERIFIED"
    assert rows[0]["verification_attempts"] == 0


def test_a_suspended_clinicians_completed_session_cannot_be_billed():
    """PRD §2.9: "The clinical safety gate is fifth: the session's clinician must
    read `billing_posture` of `BILLABLE` at the moment of completion, claim
    submission or claim resubmission, and a `GATED` or `FROZEN` posture blocks the
    operation with `ERR_CLINICIAN_NOT_BILLABLE`."

    Design: Corner/validations/session_schedule_requires_a_unjailed_clinician_posture
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    validate_success(api_client.suspend_clinician(clinician["id"], OPS))

    response = api_client.create_claim({"session_id": session["id"]}, OPS)
    error = validate_error(response, ApiErrorId.ERR_CLINICIAN_NOT_BILLABLE)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_SERVICE_NOT_ENROLLED.value

    clinician_row = get_clinician(clinician["id"])
    assert clinician_row["billing_posture"] == "FROZEN"
    assert clinician_row["status"] == "SUSPENDED"
    assert get_session_status(session["id"]) == "COMPLETED"
    assert get_enrollment_status(attach_enrollment_id(clinician["id"])) == "EFFECTIVE"


def test_a_code_outside_the_payers_allowed_set_is_a_referential_failure():
    """PRD §3.5: "Eligibility is also checked against the payer: the payer must
    read `ACTIVE` for the session's service date, the session's `cpt_code` must be
    among the payer's `allowed_cpt_codes`, and an `EFFECTIVE` enrollment must
    cover the service date for the clinician-and-payer pair"

    Design: Corner/validations/cpt_code_outside_the_payers_allowed_set_returns_service_not_enrolled
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer(allowed_cpt_codes=["90834"])
    make_rate(payer["id"], rate_cents=12_000, cpt_code="90834")
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z",
        cpt_code="90837",
    )
    add_signed_note(clinician["id"], session["id"], cpt_code="90837")
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])

    response = api_client.create_claim({"session_id": session["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_SERVICE_NOT_ENROLLED)
    assert response.status_code == 422
    assert validate_success(api_client.get_payer(payer["id"], OPS))["status"] == "ACTIVE"
    assert get_clinician(clinician["id"])["billing_posture"] == "BILLABLE", (
        "the safety gate passed, so the failure is referential"
    )
    assert get_session_status(session["id"]) == "COMPLETED"
    assert api_client.list_claims(OPS, {"session_id": session["id"]}).json()["data"] == []


def test_activating_an_enrollment_before_its_effective_date_is_an_invalid_state():
    """PRD §3.2: "An `OpsAdmin` may move an enrollment from `PENDING` to
    `EFFECTIVE` only when its `effective_from` is at or before the logical clock"

    Design: Corner/validations/enrollment_activation_before_its_effective_date_returns_invalid_state
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    credential_clinician(clinician)
    enrollment = make_enrollment(
        clinician["id"], payer["id"], effective_from="2026-12-01T00:00:00Z"
    )

    response = api_client.activate_payer_enrollment(enrollment["id"], OPS)
    error = validate_error_is_one_of(
        response, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_OUTSIDE_ENROLLMENT_WINDOW]
    )
    assert response.status_code == 409, (
        "the refusal is a declared-state conflict, not the 422 window-length rule"
    )
    assert error != ApiErrorId.ERR_ENROLLMENT_WINDOW_INVALID.value
    row = get_enrollment(enrollment["id"])
    assert row["status"] == "PENDING"
    assert row["rate_set_version_pinned"] is None
    assert get_clinician(clinician["id"])["enrolled_payer_count"] == 0


def test_locking_a_batch_before_its_period_closes_is_refused():
    """PRD §3.6: "Locking is permitted only when `period_end` is at or before the
    logical clock and at least one non-voided line exists on the batch; locking
    before the period closes, from a status other than `OPEN`, or with no
    non-voided lines is refused with `ERR_BATCH_NOT_LOCKABLE`."

    Design: Corner/validations/locking_a_batch_before_its_period_closes_returns_batch_not_lockable
    """
    set_clock("2026-06-05T00:00:00Z")
    batch = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-01T00:00:00Z",
                "period_end": "2026-06-08T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    response = api_client.lock_payout_batch(batch["id"], OPS)
    validate_error(response, ApiErrorId.ERR_BATCH_NOT_LOCKABLE)
    assert response.status_code == 409

    row = validate_success(api_client.get_payout_batch(batch["id"], OPS))
    assert row["status"] == "OPEN"
    assert row["line_count"] == 0
    assert row["total_net_cents"] == 0
    assert row["total_gross_cents"] == 0


def test_paying_a_batch_that_was_never_locked_is_refused_with_its_own_identity():
    """PRD §3.6: "Paying a locked batch is permitted only when every non-voided
    line on it is `PENDING` or already `PAID`; a batch in any status other than
    `LOCKED`, or one carrying a line in some other status, is refused with
    `ERR_BATCH_NOT_PAYABLE`."

    Design: Corner/validations/paying_an_unlocked_batch_returns_batch_not_payable
    """
    set_clock("2026-06-09T00:00:00Z")
    batch = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-01T00:00:00Z",
                "period_end": "2026-06-08T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    response = api_client.pay_payout_batch(batch["id"], OPS)
    validate_error(response, ApiErrorId.ERR_BATCH_NOT_PAYABLE)
    assert response.status_code == 409

    lock = api_client.lock_payout_batch(batch["id"], OPS)
    validate_error(lock, ApiErrorId.ERR_BATCH_NOT_LOCKABLE)
    assert validate_success(api_client.get_payout_batch(batch["id"], OPS))["status"] == "OPEN"


def test_writing_off_a_denial_inside_its_filing_window_is_refused_while_resubmission_succeeds():
    """PRD §3.5: "writing off while the clock is still strictly before the
    deadline and fewer than two resubmissions have occurred is refused with
    `ERR_WRITE_OFF_NOT_ALLOWED`."

    Design: Corner/validations/write_off_before_the_recovery_deadline_returns_write_off_not_allowed
    """
    scenario = _denied_claim_scenario()
    claim_id = scenario["claim"]["id"]

    response = api_client.write_off_claim(claim_id, OPS)
    error = validate_error(response, ApiErrorId.ERR_WRITE_OFF_NOT_ALLOWED)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_TIMELY_FILING_EXPIRED.value

    resubmitted = validate_success(api_client.resubmit_claim(claim_id, OPS))
    assert resubmitted["claim_status"] == "REPROCESSING"
    assert resubmitted["resubmission_count"] == 1


def test_a_caller_without_a_usable_role_gets_the_authentication_error_ahead_of_everything():
    """PRD §2.9: "a missing header surfaces as `ERR_UNAUTHENTICATED` rather than
    being masked by any later check."

    Design: Corner/validations/required_field_check_precedes_the_role_check_when_both_would_fail
    """
    set_clock(CLOCK_EARLY)
    response = api_client.create_claim(
        {"session_id": "00000000-0000-4000-8000-000000000003"}, ANONYMOUS
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403, (
        "Anonymous is one of the six declared roles, so the request clears "
        "authentication and is refused by the claim endpoint's own role list"
    )
    assert error["error_id"] != ApiErrorId.ERR_SESSION_NOT_FOUND.value
    assert response.json()["response_type"] == "error"


def test_the_credentialing_reviewer_role_is_segregated_from_network_administration():
    """PRD §2.1: "`OpsAdmin` may not verify a license. `ComplianceOfficer` is the
    credentialing reviewer and may only advance a clinician into credentialing and
    verify, re-verify or reset a license; it is excluded from every fiscal
    operation so that the reviewer and the payer of record are never the same
    role."

    Design: Corner/rbac/ops_admin_cannot_verify_a_license_even_though_it_administers_credentialing
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(clinician["id"])
    validate_success(
        api_client.create_malpractice_policy(
            clinician["id"], create_malpractice_policy_payload(), OPS
        ),
        201,
    )
    validate_success(api_client.submit_credentials(clinician["id"], COMPLIANCE))

    response = api_client.verify_license(clinician["id"], license_row["id"], OPS)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    assert get_clinician(clinician["id"])["status"] == "CREDENTIALING", (
        "the earlier OpsAdmin-permitted action stands"
    )
    rows = api_client.list_licenses(clinician["id"], OPS).json()["data"]
    assert rows[0]["verification_status"] == "UNVERIFIED"


def _denied_claim_scenario() -> dict:
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = validate_success(api_client.create_claim({"session_id": session["id"]}, OPS), 201)
    claim = validate_success(
        api_client.adjudicate_claim(claim["id"], {"outcome": "DENIED", "denial_code": "NOT_COVERED"}, OPS)
    )
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim}


def get_session_status(session_id: str) -> str:
    return validate_success(api_client.get_session(session_id, OPS))["status"]


def get_enrollment_status(enrollment_id: str) -> str:
    return get_enrollment(enrollment_id)["status"]


def attach_enrollment_id(clinician_id: str) -> str:
    rows = api_client.list_payer_enrollments(OPS, {"clinician_id": clinician_id}).json()["data"]
    return rows[0]["id"]