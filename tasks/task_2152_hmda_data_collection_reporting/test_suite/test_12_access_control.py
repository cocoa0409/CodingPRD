"""Header authentication and the narrow write surface each role is granted."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certify_payload,
    create_application_payload,
    create_edit_run_payload,
    create_institution,
    make_compliance_officer_headers,
    make_examiner_headers,
    make_system_admin_headers,
    no_auth_headers,
    read_institution,
    read_submission,
    setup_attached_submission_on_empty_register,
    validate_error,
    validate_paginated,
)


def test_a_request_with_no_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the capacity in which the
    caller is acting. If either header is absent, or if the value of `X-User-Role`
    is not one of the six roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401. This check runs before anything else,
    including the existence of the resources named in the path."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    institution = create_institution()

    validate_error(
        api.get_institution(institution["id"], no_auth_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_a_loan_officer_may_not_run_the_edit_battery(api):
    """PRD §4: "POST | `/hmda/edit-runs` | Run the syntactical, validity, quality
    and macro edit battery over the institution's register snapshot |
    ComplianceAnalyst"
    PRD §2.1: "A caller whose role is authenticated but who is not among the roles
    authorised for the endpoint receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

    Design: Corner/validations/loan_officer_cannot_create_edit_runs
    """
    institution = create_institution()

    validate_error(
        api.create_edit_run(
            create_edit_run_payload(institution["id"]), TEST_USERS["loan_officer_headers"]
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    rows, meta = validate_paginated(
        api.list_institution_edit_runs(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_an_examiner_may_not_certify_a_submission(api):
    """PRD §2.1: "`Examiner` is the regulator-side reviewer. It may read everything
    on the platform and it alone may accept or reject a filed submission."
    PRD §4: "POST | `/hmda/submissions/{id}/certify` | Officer attests to the
    register; freezes the final record count and locks the institution for filing |
    ComplianceOfficer"

    Design: Corner/rbac/examiner_cannot_certify_a_submission
    """
    institution, _run, submission = setup_attached_submission_on_empty_register()

    validate_error(
        api.certify_submission(
            submission["id"],
            certify_payload(attestation_text="Examiner attempting to certify."),
            make_examiner_headers(),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    assert read_submission(submission["id"])["status"] == "EDITS_ATTACHED"
    assert read_institution(institution["id"])["filing_posture"] == "OPEN"


def test_a_compliance_officer_may_not_open_register_records(api):
    """PRD §2.1: "`LoanOfficer` is the front-line originator who opens register
    records, captures and amends fields, advances the record through the capture
    stages, records the action taken, collects applicant demographics, and geocodes
    the secured property."
    PRD §2.1: "Write capability is narrow and does not overlap between roles."

    Design: Corner/rbac/compliance_officer_cannot_create_applications
    """
    institution = create_institution()

    validate_error(
        api.create_application(
            create_application_payload(institution["id"]), make_compliance_officer_headers()
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    assert read_institution(institution["id"])["total_application_count"] == 0


def test_a_system_admin_may_not_run_the_edit_battery(api):
    """PRD §2.1: "`SystemAdmin` is the platform operator: it onboards reporting
    institutions, loads census reference data, and drives the logical clock. Those
    three capabilities belong to `SystemAdmin` alone."
    PRD §2.1: "A caller whose role is authenticated but who is not among the roles
    authorised for the endpoint receives `ERR_FORBIDDEN_ROLE` with HTTP 403."

    Design: Corner/rbac/system_admin_cannot_create_edit_runs
    """
    institution = create_institution()

    validate_error(
        api.create_edit_run(
            create_edit_run_payload(institution["id"]), make_system_admin_headers()
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    rows, meta = validate_paginated(
        api.list_institution_edit_runs(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0
