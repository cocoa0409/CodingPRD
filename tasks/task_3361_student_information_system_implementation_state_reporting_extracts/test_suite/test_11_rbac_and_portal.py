"""RBAC: caller-context checks, role denial, PortalUser ownership scope, and
portal-account defaults and terminal lockdown."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_live_district,
    create_portal_account,
    create_school_year,
    create_student,
    create_student_payload,
    make_portal_user_headers,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_headers_on_student_create_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside this
    declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`."
    PRD §2.7: "Caller context. `X-User-ID` and `X-User-Role` are present and the role
    is one of the declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_on_student_create_returns_unauthenticated
    """
    reset_clock()
    # Issued with no X-User-ID / X-User-Role headers at all.
    res = api.create_student(
        create_student_payload(NON_EXISTENT_UUID, student_number="S900",
                               first_name="No", last_name="Auth"),
        {},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                   expected_status=400)


def test_portal_role_beats_existence_on_unknown_section_returns_forbidden(
        api, portal_user_headers):
    """PRD §2.7: "Every request passes through a fixed sequence of validation stages,
    and the first failing stage determines the error returned — earlier stages mask
    later ones."
    PRD §2.1: "A `PortalUser` holds no write surface at all and may read exactly one
    resource: the portal account whose `id` equals the caller's own `X-User-ID`."

    Design: Corner/validations/portal_role_beats_existence_on_unknown_section_returns_forbidden
    """
    reset_clock()
    # PortalUser reading a section id that does not exist: authorization (stage 3)
    # precedes existence (stage 4), so the outcome is 403, never 404.
    res = api.get_section(NON_EXISTENT_UUID, portal_user_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_portal_user_reads_own_account_but_not_others(api, district_admin_headers):
    """PRD §2.1: "When `X-User-Role` is `PortalUser`, the `X-User-ID` value is the
    `id` of the acting `PortalAccount`, and ownership checks compare the requested
    account's `id` to `X-User-ID`: a `PortalUser` request targeting any other portal
    account is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/portal_user_reads_own_account_but_not_others
    """
    reset_clock()
    district = create_live_district()
    student_a = create_student(district["id"], student_number="S001")
    student_b = create_student(
        district["id"], student_number="S002", first_name="Bo", last_name="Reyes",
        birth_date="2013-09-09T00:00:00Z", entry_grade_level="KG")
    account_a = create_portal_account(
        student_a["id"], account_type="STUDENT", access_level="FULL")
    account_b = create_portal_account(
        student_b["id"], account_type="STUDENT", access_level="GRADES_ONLY")

    own_headers = make_portal_user_headers(account_a["id"])
    own = validate_success(api.get_portal_account(account_a["id"], own_headers), 200)
    assert own["id"] == account_a["id"]

    res = api.get_portal_account(account_b["id"], own_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_portal_user_cannot_create_students(api, portal_user_headers,
                                            registrar_headers):
    """PRD §2.1: "A `PortalUser` holds no write surface at all and may read exactly
    one resource: the portal account whose `id` equals the caller's own `X-User-ID`."
    PRD §2.1: "A well-identified caller whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/portal_user_cannot_create_students
    """
    reset_clock()
    district = create_live_district()
    res = api.create_student(
        create_student_payload(district["id"], student_number="S900",
                               first_name="No", last_name="Access"),
        portal_user_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    data, meta = validate_paginated(
        api.list_students(registrar_headers, params={"district_id": district["id"]}))
    assert meta["total_count"] == 0


def test_state_reporter_cannot_open_school_year(api, state_reporter_headers,
                                                district_admin_headers):
    """PRD §2.1: "A `DistrictAdmin` — the district implementation office — owns
    school years, rollover runs, portal account provisioning, and integration feeds."
    PRD §2.1: "A well-identified caller whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/state_reporter_cannot_open_school_year
    """
    reset_clock()
    district = create_live_district()
    year = create_school_year(district["id"])  # PLANNING

    res = api.open_school_year(year["id"], state_reporter_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = validate_success(api.get_school_year(year["id"], district_admin_headers), 200)
    assert after["status"] == "PLANNING", "a forbidden open must not move the year"


def test_portal_account_create_defaults_grade_visibility(api, district_admin_headers):
    """PRD §3.8: "The `grade_visibility` setting — `ALL_GRADES`, `CURRENT_TERM_ONLY`,
    or `HIDDEN` — defaults to `CURRENT_TERM_ONLY` when omitted."
    PRD §3.8: "Accounts begin `INVITED`".

    Design: Corner/entities/portal_account_create_defaults_grade_visibility
    """
    reset_clock()
    district = create_live_district()
    student = create_student(district["id"])

    res = api.create_portal_account(
        {"student_id": student["id"], "account_type": "PARENT",
         "access_level": "GRADES_ONLY"},
        district_admin_headers,
    )
    account = validate_success(res, 201)
    assert account["grade_visibility"] == "CURRENT_TERM_ONLY", \
        "the omitted grade_visibility stores the declared default"
    assert account["status"] == "INVITED"


def test_portal_account_revoked_rejects_update_access(api, district_admin_headers):
    """PRD §3.8: "revocation moves `INVITED` or `ACTIVE` to the terminal `REVOKED`
    (an already-`REVOKED` account rejects further transitions and updates with
    `ERR_PORTAL_ACCOUNT_REVOKED`)."

    Design: Corner/state_machines/portal_account_revoked_rejects_update_access
    """
    reset_clock()
    district = create_live_district()
    student = create_student(district["id"])
    account = create_portal_account(
        student["id"], account_type="PARENT", access_level="FULL")
    validate_success(api.revoke_portal_account(account["id"], district_admin_headers), 200)

    res = api.update_portal_account_access(
        account["id"], {"grade_visibility": "ALL_GRADES"}, district_admin_headers)
    validate_error(res, ApiErrorId.ERR_PORTAL_ACCOUNT_REVOKED, expected_status=409)

    after = validate_success(
        api.get_portal_account(account["id"], district_admin_headers), 200)
    assert after["status"] == "REVOKED"
    assert after["grade_visibility"] == "CURRENT_TERM_ONLY", \
        "the rejected update must not change grade_visibility"
