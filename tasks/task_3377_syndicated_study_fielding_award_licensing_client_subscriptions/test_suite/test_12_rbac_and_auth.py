"""Role-based access control and authentication precedence (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    create_methodology_payload,
    create_study,
    create_study_payload,
    get_study,
    make_client_user_headers,
    register_client,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["study_admin_headers"]
FOPS = TEST_USERS["field_ops_headers"]


def test_pin_forbidden_for_fieldops(api, field_ops_headers):
    """PRD §2.1: "A request whose role is declared but not authorized for the
    target endpoint — or that fails an ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST /research/methodology-versions/{id}/pin ... MethodologyLead"
    (the pin endpoint is authorized for MethodologyLead only).

    Design: Corner/rbac/pin_forbidden_for_fieldops
    """
    study = create_study()
    # Draft a methodology as the right role; the forbidden act is the pin.
    mv = validate_success(
        api.create_methodology_version(
            create_methodology_payload(study["id"]), TEST_USERS["methodology_lead_headers"]
        ),
        expected_status=201,
    )
    resp = api.pin_methodology_version(
        mv["id"], {"expected_study_version": study["version"]}, field_ops_headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    mv_after = validate_success(api.get_methodology_version(mv["id"], TEST_USERS["methodology_lead_headers"]))
    assert mv_after["status"] == "DRAFT"
    after = get_study(study["id"])
    assert after["status"] == "DRAFT" and after["version"] == 1


def test_press_kit_forbidden_for_client_user(api):
    """PRD §2.1: "A request whose role is declared but not authorized for the
    target endpoint — or that fails an ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "GET /research/studies/{id}/press-kit ... PressUser, StudyAdmin"
    (the press-kit endpoint is authorized for PressUser and StudyAdmin only).

    Design: Corner/rbac/press_kit_forbidden_for_client_user
    """
    study = create_study(min_sample_per_brand=1)
    client = register_client()
    resp = api_client.get_press_kit(study["id"], make_client_user_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_unauthenticated_when_role_header_missing(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the role under which the user acts. A
    request missing either header, or carrying an `X-User-Role` value that is not
    one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_when_role_header_missing
    """
    set_clock()
    resp = api_client.create_study(
        create_study_payload(),
        {"X-User-ID": "u_anon", "Content-Type": "application/json"},  # no X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    _, meta = validate_paginated(api_client.list_studies(ADMIN))
    assert meta["total_count"] == 0, "no study may be created"
