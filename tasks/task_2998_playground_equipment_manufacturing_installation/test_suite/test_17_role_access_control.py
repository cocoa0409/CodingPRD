"""Role and identity gating: exclusive denials, shared admits, duty separation.

Every test in this module starts against an empty database with the logical
clock at 2026-08-01T00:00:00Z and builds its own preconditions.
"""

import pytest

from test_helpers import (
    AUDITOR_2_USER_ID,
    AUDITOR_USER_ID,
    CONSULTANT_USER_ID,
    OFFICER_2_USER_ID,
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_paginated_list,
    get_success_data,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_installer_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

# Each entry pairs an operation with a role the endpoint does not list, and a
# syntactically valid identifier that resolves to nothing at all.
DENIED_OPERATIONS = [
    (
        "activate_standard",
        "manufacturer_admin_headers",
        "11111111-1111-4111-8111-111111111111",
    ),
    (
        "certify_component_model",
        "design_consultant_headers",
        "22222222-2222-4222-8222-222222222222",
    ),
    (
        "start_consultation",
        "client_representative_headers",
        "33333333-3333-4333-8333-333333333333",
    ),
    (
        "validate_placement",
        "safety_auditor_headers",
        "44444444-4444-4444-8444-444444444444",
    ),
    (
        "accept_quote",
        "design_consultant_headers",
        "55555555-5555-4555-8555-555555555555",
    ),
    (
        "collect_pledge",
        "manufacturer_admin_headers",
        "66666666-6666-4666-8666-666666666666",
    ),
    (
        "start_job",
        "safety_auditor_headers",
        "77777777-7777-4777-8777-777777777777",
    ),
    (
        "certify_compliance",
        "installer_operator_headers",
        "88888888-8888-4888-8888-888888888888",
    ),
    (
        "ship_order",
        "design_consultant_headers",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ),
    (
        "delete_placement",
        "client_representative_headers",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ),
]

# Absent means the header is not sent at all; blank means it is sent as the
# empty string.  A run of spaces is never sent: it can be refused before the
# request ever leaves the client.
UNUSABLE_IDENTITY_HEADERS = [
    ("user_id_absent", headers_without_user_id("ComplianceOfficer")),
    ("role_absent", headers_without_role(OFFICER_USER_ID)),
    ("user_id_blank", headers_with_empty_user_id("ComplianceOfficer")),
    ("role_blank", headers_with_empty_role(OFFICER_USER_ID)),
]


@pytest.mark.parametrize(
    "method_name, headers_key, unresolvable_id", DENIED_OPERATIONS
)
def test_unlisted_role_is_refused_before_the_path_is_resolved(
    method_name, headers_key, unresolvable_id
):
    """An unlisted role gets 403 even though the path identifier resolves to nothing.

    PRD: "a caller presenting a valid but unlisted role is refused with
    `ERR_FORBIDDEN_ROLE`, and role membership is checked before any payload
    validation, existence check or state check"

    Design: Corner/rbac/exclusive_operation_denial_matrix_and_header_validation
    """
    response = getattr(api_client, method_name)(
        unresolvable_id, TEST_USERS[headers_key]
    )

    assert response.status_code == 403, (
        f"expected 403 from {method_name} for an unlisted role, got "
        f"{response.status_code}: role membership must outrank path resolution"
    )
    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert set(error.keys()) == {"error_id", "message"}, (
        f"expected exactly error_id and message in the error data, got {sorted(error)}"
    )


@pytest.mark.parametrize("variant, headers", UNUSABLE_IDENTITY_HEADERS)
def test_absent_or_blank_identity_headers_are_unauthenticated(variant, headers):
    """A missing or empty identity header fails authentication and writes nothing.

    PRD: "If either header is absent, or present but empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/exclusive_operation_denial_matrix_and_header_validation
    """
    standard = fx.register_standard()
    assert standard["status"] == "DRAFT", (
        f"expected a DRAFT edition to act on, got {standard['status']}"
    )

    response = api_client.activate_standard(standard["id"], headers)

    assert response.status_code == 401, (
        f"expected 401 for the {variant} case, got {response.status_code}"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    after = get_success_data(
        api_client.get_standard(
            standard["id"], TEST_USERS["compliance_officer_headers"]
        )
    )
    assert after["status"] == "DRAFT", (
        f"expected the edition to stay DRAFT after the {variant} case, "
        f"got {after['status']}"
    )
    assert after["version"] == standard["version"], (
        f"expected version {standard['version']} after the {variant} case, "
        f"got {after['version']}"
    )


def test_unrecognised_role_name_fails_authentication_not_authorisation():
    """A role name outside the six declared roles answers 401, never 403.

    PRD: "an unrecognised role name is an authentication failure, not an
    authorisation failure"

    Design: Corner/rbac/exclusive_operation_denial_matrix_and_header_validation
    """
    standard = fx.register_standard()

    response = api_client.activate_standard(
        standard["id"], make_headers(OFFICER_USER_ID, "SiteInspector")
    )

    assert response.status_code == 401, (
        f"expected 401 for an undeclared role name, got {response.status_code}: "
        "role recognition is checked before endpoint membership"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    after = get_success_data(
        api_client.get_standard(
            standard["id"], TEST_USERS["compliance_officer_headers"]
        )
    )
    assert after["status"] == "DRAFT", (
        f"expected the edition to stay DRAFT, got {after['status']}"
    )
    assert after["version"] == standard["version"], (
        f"expected version {standard['version']}, got {after['version']}"
    )


def test_listed_role_passes_the_role_gate_and_fails_only_on_path_resolution():
    """A role the endpoint does list reaches path resolution and answers 404.

    PRD: "Path segments are resolved strictly left to right, and the first
    segment that fails to resolve determines the error"

    Design: Corner/rbac/exclusive_operation_denial_matrix_and_header_validation
    """
    response = api_client.get_standard(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        TEST_USERS["installer_operator_headers"],
    )

    assert response.status_code == 404, (
        f"expected 404 for a listed role reading an unknown edition, got "
        f"{response.status_code}"
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_NOT_FOUND.value)


def test_the_exclusive_operation_admits_its_own_declared_role():
    """The same activation endpoint works for the one role it lists.

    PRD: "Activation is a `ComplianceOfficer` privilege and moves an edition
    `DRAFT → ACTIVE`."

    Design: Corner/rbac/exclusive_operation_denial_matrix_and_header_validation
    """
    standard = fx.register_standard()

    response = api_client.activate_standard(
        standard["id"], TEST_USERS["compliance_officer_headers"]
    )

    activated = validate_success(response)
    assert activated["status"] == "ACTIVE", (
        f"expected ACTIVE after the officer activates the edition, got "
        f"{activated['status']}"
    )
    assert activated["version"] == 2, (
        f"expected version 2 after activation, got {activated['version']}"
    )


def test_standard_registration_admits_both_of_its_declared_roles():
    """Both declared roles create a new edition of the same family, each in DRAFT.

    PRD: "Registering one is a records-keeping act, open to both
    `ManufacturerAdmin` and `ComplianceOfficer` operators"

    Design: Corner/rbac/shared_operations_admit_each_of_their_declared_roles
    """
    active = fx.create_active_standard()

    by_admin = validate_success(
        api_client.create_standard(
            f.standard_payload(edition_year=2025, effective_from="2027-01-01"),
            TEST_USERS["manufacturer_admin_headers"],
        ),
        201,
    )
    by_officer = validate_success(
        api_client.create_standard(
            f.standard_payload(edition_year=2026, effective_from="2027-01-01"),
            TEST_USERS["compliance_officer_headers"],
        ),
        201,
    )

    assert by_admin["status"] == "DRAFT", (
        f"expected DRAFT from the admin registration, got {by_admin['status']}"
    )
    assert by_officer["status"] == "DRAFT", (
        f"expected DRAFT from the officer registration, got {by_officer['status']}"
    )
    assert by_admin["id"] != by_officer["id"], (
        "expected two distinct editions from the two roles"
    )

    rows, _meta = assert_paginated_list(
        api_client.list_standards(
            TEST_USERS["compliance_officer_headers"], {"status": "ACTIVE"}
        ),
        1,
    )
    assert rows[0]["id"] == active["id"], (
        "expected the originally activated edition to remain the only ACTIVE one"
    )


def test_pledge_creation_admits_both_of_its_declared_roles():
    """Both declared roles record a pledge, and neither pledge moves any money.

    PRD: "A recorded pledge is born `PLEDGED` and returned with HTTP 201, and —
    importantly — it contributes nothing to the project's money until it is
    collected."

    Design: Corner/rbac/shared_operations_admit_each_of_their_declared_roles
    """
    fx.create_active_standard()
    project = fx.create_project_in_consultation()

    by_client = validate_success(
        api_client.create_pledge(
            project["id"],
            f.pledge_payload(amount_cents=20000, pledged_at="2026-08-01"),
            TEST_USERS["client_representative_headers"],
        ),
        201,
    )
    by_consultant = validate_success(
        api_client.create_pledge(
            project["id"],
            f.pledge_payload(amount_cents=30000, pledged_at="2026-08-01"),
            TEST_USERS["design_consultant_headers"],
        ),
        201,
    )

    assert by_client["status"] == "PLEDGED", (
        f"expected PLEDGED from the client pledge, got {by_client['status']}"
    )
    assert by_consultant["status"] == "PLEDGED", (
        f"expected PLEDGED from the consultant pledge, got {by_consultant['status']}"
    )
    assert by_client["id"] != by_consultant["id"], (
        "expected two distinct pledge rows from the two roles"
    )

    assert_paginated_list(
        api_client.list_project_pledges(
            project["id"], TEST_USERS["client_representative_headers"]
        ),
        2,
    )
    refreshed = fx.get_project(project["id"])
    assert refreshed["funds_collected_cents"] == 0, (
        f"expected 0 collected cents while both pledges are merely PLEDGED, got "
        f"{refreshed['funds_collected_cents']}"
    )


@pytest.mark.parametrize(
    "headers_key", ["client_representative_headers", "compliance_officer_headers"]
)
def test_warranty_claim_admits_both_roles_and_answers_the_business_code(headers_key):
    """Both declared roles reach the installation gate, so neither is refused on role.

    PRD: "a claim against an uninstalled project is refused with
    `ERR_PROJECT_NOT_INSTALLED` (HTTP 422)"

    Design: Corner/rbac/shared_operations_admit_each_of_their_declared_roles
    """
    scenario = fx.setup_single_placement_design()

    response = api_client.create_warranty_claim(
        f.warranty_claim_payload(
            scenario["project"]["id"],
            scenario["placement"]["id"],
            "2026-08-01",
            quantity=1,
        ),
        TEST_USERS[headers_key],
    )

    assert response.status_code == 422, (
        f"expected 422 for {headers_key}, got {response.status_code}: a shared "
        "role must reach the business gate rather than the role gate"
    )
    error = validate_error(response, ApiErrorId.ERR_PROJECT_NOT_INSTALLED.value)
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value, (
        f"{headers_key} must not be refused on role membership"
    )


def test_compliance_certification_refuses_the_projects_own_consultant_identity():
    """The certifying officer identity may not be the identity that created the project.

    PRD: "the `ComplianceOfficer` who certifies a project's compliance must not be
    the `DesignConsultant` who created it"

    Design: Corner/rbac/segregation_of_duties_separates_certifier_job_owner_and_second_auditor
    """
    scenario = fx.setup_design_approved_project()
    project = scenario["project"]
    assert project["consultant_user_id"] == CONSULTANT_USER_ID, (
        f"expected the creating consultant on record, got "
        f"{project['consultant_user_id']}"
    )
    assert project["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED before certification, got {project['design_status']}"
    )

    response = api_client.certify_compliance(
        project["id"], make_headers(CONSULTANT_USER_ID, "ComplianceOfficer")
    )

    assert response.status_code == 403, (
        f"expected 403 when the officer identity equals consultant_user_id, got "
        f"{response.status_code}"
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    untouched = fx.get_project(project["id"])
    assert untouched["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED after the refusal, got {untouched['design_status']}"
    )
    assert untouched["compliance_status"] == "NOT_ASSESSED", (
        f"expected NOT_ASSESSED after the refusal, got "
        f"{untouched['compliance_status']}"
    )
    assert untouched["version"] == project["version"], (
        f"expected version {project['version']} after the refusal, got "
        f"{untouched['version']}"
    )

    certified = validate_success(
        api_client.certify_compliance(
            project["id"], make_headers(OFFICER_2_USER_ID, "ComplianceOfficer")
        )
    )
    assert certified["design_status"] == "CERTIFIED", (
        f"expected CERTIFIED once a different identity certifies, got "
        f"{certified['design_status']}"
    )
    assert certified["compliance_status"] == "COMPLIANT", (
        f"expected COMPLIANT once a different identity certifies, got "
        f"{certified['compliance_status']}"
    )


def test_installer_operator_may_not_drive_another_companys_booking():
    """A job trigger from a different company is refused on ownership, then the owner drives it.

    PRD: "every one of the three operator-driven job triggers compares the acting
    `X-User-ID` against the job's `installer_id` and refuses a mismatch with
    `ERR_NOT_JOB_OWNER`"

    Design: Corner/rbac/segregation_of_duties_separates_certifier_job_owner_and_second_auditor
    """
    scenario = fx.setup_job_scheduled()
    job = scenario["job"]
    installer = scenario["installer"]

    assert job["status"] == "SCHEDULED", (
        f"expected SCHEDULED before any start attempt, got {job['status']}"
    )
    assert job["booked_crew_days"] == 12, (
        f"expected 12 booked crew days, got {job['booked_crew_days']}"
    )
    a.assert_booked_crew_days(job)
    assert installer["committed_crew_days"] == 12, (
        f"expected the booked company to carry 12 committed crew days, got "
        f"{installer['committed_crew_days']}"
    )

    other = fx.create_installer(
        company_name="Southgate Play Crews",
        certification_level="CERTIFIED",
        certified_categories=["POST"],
        region_code="TX",
    )
    assert other["committed_crew_days"] == 0, (
        f"expected the second company to hold no bookings, got "
        f"{other['committed_crew_days']}"
    )

    response = api_client.start_job(
        job["id"], make_installer_operator_headers(other["id"])
    )

    assert response.status_code == 403, (
        f"expected 403 when a different company starts the job, got "
        f"{response.status_code}: ownership is compared before the job's own "
        "start-date eligibility, and the clock is still 2026-08-01"
    )
    validate_error(response, ApiErrorId.ERR_NOT_JOB_OWNER.value)

    untouched = fx.get_job(job["id"])
    assert untouched["status"] == "SCHEDULED", (
        f"expected SCHEDULED after the refusal, got {untouched['status']}"
    )
    assert untouched["version"] == job["version"], (
        f"expected version {job['version']} after the refusal, got "
        f"{untouched['version']}"
    )

    fx.set_clock_to_date("2026-08-10")
    started = fx.start_job(job["id"], installer["id"])
    assert started["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS once the owning company starts it, got "
        f"{started['status']}"
    )
    completed = fx.complete_job(job["id"], installer["id"])
    assert completed["status"] == "INSPECTION_PENDING", (
        f"expected INSPECTION_PENDING once the owning company reports the work "
        f"finished, got {completed['status']}"
    )


def test_post_install_audit_refuses_the_recorded_install_inspector():
    """The recorded install inspector cannot audit the same job; a second auditor can.

    PRD: "Filing a post-installation audit additionally requires that the acting
    `X-User-ID` differ from the job's recorded `install_inspector_user_id`, with a
    match refused as `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_separates_certifier_job_owner_and_second_auditor
    """
    scenario = fx.setup_installed_project()
    job = scenario["job"]
    inspection = scenario["inspection"]

    assert inspection["sequence_number"] == 1, (
        f"expected the first record at sequence number 1, got "
        f"{inspection['sequence_number']}"
    )
    assert inspection["performed_by_user_id"] == AUDITOR_USER_ID, (
        f"expected {AUDITOR_USER_ID} on the installation inspection, got "
        f"{inspection['performed_by_user_id']}"
    )
    assert job["status"] == "AUDIT_PENDING", (
        f"expected AUDIT_PENDING after a passing installation inspection, got "
        f"{job['status']}"
    )
    assert job["install_inspector_user_id"] == AUDITOR_USER_ID, (
        f"expected {AUDITOR_USER_ID} recorded as the install inspector, got "
        f"{job['install_inspector_user_id']}"
    )
    assert scenario["project"]["design_status"] == "INSTALLED", (
        f"expected INSTALLED, got {scenario['project']['design_status']}"
    )

    audit_body = f.inspection_payload(
        kind="POST_INSTALL_AUDIT",
        result="PASS",
        deficiency_count=0,
        fall_height_measured_cm=0,
        surfacing_depth_measured_cm=30,
    )

    refused = api_client.file_inspection(
        job["id"], audit_body, TEST_USERS["safety_auditor_headers"]
    )
    assert refused.status_code == 403, (
        f"expected 403 when the install inspector audits its own job, got "
        f"{refused.status_code}"
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_pending = fx.get_job(job["id"])
    assert still_pending["status"] == "AUDIT_PENDING", (
        f"expected AUDIT_PENDING after the refusal, got {still_pending['status']}"
    )
    assert_paginated_list(
        api_client.list_job_inspections(
            job["id"], TEST_USERS["compliance_officer_headers"]
        ),
        1,
    )

    accepted = validate_success(
        api_client.file_inspection(
            job["id"], audit_body, TEST_USERS["safety_auditor_2_headers"]
        ),
        201,
    )
    assert accepted["sequence_number"] == 2, (
        f"expected sequence number 2, got {accepted['sequence_number']}: the "
        "refused attempt must consume no sequence number"
    )
    assert accepted["performed_by_user_id"] == AUDITOR_2_USER_ID, (
        f"expected {AUDITOR_2_USER_ID} on the accepted audit, got "
        f"{accepted['performed_by_user_id']}"
    )

    audited_job = fx.get_job(job["id"])
    assert audited_job["status"] == "AUDIT_PASSED", (
        f"expected AUDIT_PASSED, got {audited_job['status']}"
    )
    audited_project = fx.get_project(scenario["project"]["id"])
    assert audited_project["design_status"] == "AUDITED", (
        f"expected AUDITED, got {audited_project['design_status']}"
    )
    assert audited_project["compliance_status"] == "COMPLIANT", (
        f"expected COMPLIANT, got {audited_project['compliance_status']}"
    )
    assert_paginated_list(
        api_client.list_job_inspections(
            job["id"], TEST_USERS["compliance_officer_headers"]
        ),
        2,
    )
