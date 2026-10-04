"""Degree reporting, sealing gating, and revocation lockdown (PRD 3.6)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error,
    advance_clock, create_institution_with_registrars,
    setup_period_scenario, setup_student_with_file, upload_file,
    list_file_entries, enrollment_row,
    report_degree, seal_degree, make_certifier_headers,
)

OPS = TEST_USERS["ops_headers"]


def _suspended_institution_with_reported_degree(api):
    """A REPORTED degree whose institution is then ops-suspended."""
    ctx = setup_student_with_file()
    degree = report_degree(ctx, ctx["student_id"])
    ctx["degree_id"] = degree["id"]
    validate_success(api_client.suspend_institution(ctx["inst_id"], OPS), 200)
    return ctx


def test_seal_rejected_while_institution_suspended(api):
    """PRD section 3.6: "A `RegistrarCertifier` seals a `REPORTED` record —
    anything else fails with `ERR_INVALID_STATE` — and only when the
    certifier's institution matches the degree's
    (`ERR_CROSS_INSTITUTION_ACCESS`), the institution is `ACTIVE`
    (`ERR_INSTITUTION_SUSPENDED`), an `ACTIVE` participation agreement
    covers the current instant (`ERR_AGREEMENT_LAPSED`)".

    Design: Difficulty/cross_entity_state_dependency/degree_seal_requires_institution_active
    """
    ctx = _suspended_institution_with_reported_degree(api)
    resp = api_client.seal_degree_record(
        ctx["degree_id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTITUTION_SUSPENDED)


def test_seal_succeeds_after_reinstatement(api):
    """PRD section 3.6: "Sealing stamps `sealed_at` and moves the record
    `REPORTED` → `SEALED`."
    PRD section 3.1: "reinstatement returns the institution to `ACTIVE` with
    `suspension_reason` cleared to `NONE`."

    Design: Difficulty/cross_entity_state_dependency/degree_seal_requires_institution_active
    """
    ctx = _suspended_institution_with_reported_degree(api)
    degree = validate_success(
        api_client.get_degree_record(ctx["degree_id"], OPS), 200,
    )
    assert degree["status"] == "REPORTED", "the failed seal left no transition"
    validate_success(api_client.reinstate_institution(ctx["inst_id"], OPS), 200)
    sealed = seal_degree(ctx, ctx["degree_id"])
    assert sealed["status"] == "SEALED", (
        "with the institution ACTIVE again and the agreement covering now, "
        "the same seal succeeds"
    )


def test_err_institution_non_compliant_blocks_seal(api):
    """PRD section 3.6: "the institution's `compliance_standing` is anything
    other than `NON_COMPLIANT`: a non-compliant institution's sealing attempt
    is rejected with `ERR_INSTITUTION_NON_COMPLIANT` (HTTP 422)."
    PRD section 3.2: "If any of those periods is `DELINQUENT`, the
    institution becomes `NON_COMPLIANT`".

    Design: Corner/errors/err_institution_non_compliant_blocks_seal
    """
    ctx = setup_period_scenario()
    file = upload_file(ctx, [enrollment_row()])
    student_id = list_file_entries(file["id"])[0]["student_id"]
    degree = report_degree(ctx, student_id)
    # Never certify: the period will close DELINQUENT.
    advance_clock("2027-01-04T00:00:00Z")
    inst = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert inst["compliance_standing"] == "NON_COMPLIANT"
    resp = api_client.seal_degree_record(
        degree["id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTITUTION_NON_COMPLIANT)
    degree = validate_success(
        api_client.get_degree_record(degree["id"], OPS), 200,
    )
    assert degree["status"] == "REPORTED"


def test_degree_revoked_terminal_lockdown(api):
    """PRD section 3.6: "Revocation is terminal and one-way: a certifier of
    the same institution revokes a `SEALED` record, moving it `SEALED` →
    `REVOKED`."
    PRD section 2.9: "terminal states accept no further transitions, and an
    action fired against a resource in the wrong state — including re-firing
    an action whose effect has already been applied, or acting on a resource
    in a terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/degree_revoked_terminal_lockdown
    """
    ctx = setup_student_with_file()
    degree = report_degree(ctx, ctx["student_id"])
    seal_degree(ctx, degree["id"])
    resp = api_client.revoke_degree_record(
        degree["id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_success(resp, 200)
    seal_again = api_client.seal_degree_record(
        degree["id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(seal_again, ApiErrorId.ERR_INVALID_STATE)
    revoke_again = api_client.revoke_degree_record(
        degree["id"], make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(revoke_again, ApiErrorId.ERR_INVALID_STATE)
    degree = validate_success(
        api_client.get_degree_record(degree["id"], OPS), 200,
    )
    assert degree["status"] == "REVOKED"


def test_err_degree_not_found(api):
    """PRD section 2.8: "Each kind of unresolved reference reports its own
    error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or
    `ERR_DATASET_NOT_FOUND`, each HTTP 404".

    Design: Corner/errors/err_degree_not_found
    """
    ctx = create_institution_with_registrars()
    resp = api_client.seal_degree_record(
        NON_EXISTENT_UUID, make_certifier_headers(ctx["cert_uid"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEGREE_NOT_FOUND)
