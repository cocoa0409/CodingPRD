"""Corner breadth index (rbac): exclusive operations refuse callers from the
wrong role with the priority-2 permission error.
"""
from test_helpers import (
    INSPECTOR_HEADERS,
    OWNER_REPRESENTATIVE_HEADERS,
    ApiClient,
    ApiErrorId,
    certify_payload,
    coating_system_payload,
    create_applicator,
    create_coating_system,
    create_program,
    enroll_qualification,
    make_applicator_rep_headers,
    project_payload,
    read_qualification,
    validate_error,
)


def test_applicator_rep_cannot_create_coating_system(api: ApiClient):
    """PRD §2.1: "Each write endpoint is restricted to a named subset of
    these roles (enumerated in §4); a request whose role is not authorized
    for the endpoint it targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "A `TechnicalServiceEngineer` represents the manufacturer's
    technical service organization and exclusively owns coating-system
    registration, revision, and obsolescence".

    Design: Corner/rbac/applicator_rep_cannot_create_coating_system
    """
    response = api.create_coating_system(
        coating_system_payload(system_code="SW-DENY-1"),
        make_applicator_rep_headers("00000000-0000-4000-8000-0000000000ab"),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_inspector_cannot_create_project(api: ApiClient):
    """PRD §2.1: "a request whose role is not authorized for the endpoint it
    targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "A `ProjectEngineer` is the owner-side engineer who exclusively
    creates, completes, and cancels projects".

    Design: Corner/rbac/inspector_cannot_create_project
    """
    response = api.create_project(
        project_payload(project_name="Inspector Project", warranty_budget_cents=1_000),
        INSPECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_owner_rep_cannot_certify_qualification(api: ApiClient):
    """PRD §2.1: "a request whose role is not authorized for the endpoint it
    targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "A `TechnicalServiceEngineer` represents the manufacturer's
    technical service organization and exclusively owns coating-system
    registration, revision, and obsolescence; qualification-program creation;
    certification, suspension, reinstatement, and revocation of applicator
    qualifications".

    Design: Corner/rbac/owner_rep_cannot_certify_qualification
    """
    applicator = create_applicator(api, company_name="Deny Cert Coaters", contact_email="dc@coaters.example")
    system = create_coating_system(api, system_code="SW-DENY-CERT")
    program = create_program(api, system["id"], program_code="QP-DENY-CERT")
    qualification = enroll_qualification(api, applicator["id"], program["id"])

    response = api.certify_qualification(
        applicator["id"], qualification["id"],
        certify_payload(applicator["version"]),
        OWNER_REPRESENTATIVE_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    assert read_qualification(api, applicator["id"], qualification["id"])["status"] == "CANDIDATE"
