"""Authentication and role authorization (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    create_judge_payload,
    create_rodeo_payload,
    create_vet_report_payload,
    get_success_data,
    make_contestant_headers,
    register_contestant,
    TEST_USERS,
    validate_error,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]
BOX = TEST_USERS["box_office_headers"]


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "Every request carries two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act. ... A request with missing headers or an
    unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api.create_rodeo(
        create_rodeo_payload(name="No Auth Rodeo", city="NA"),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_judge_create_forbidden_for_contestant_role(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint or
    action is rejected with `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4: POST /api/judges is authorized for CommitteeAdmin only.

    Design: Corner/validations/judge_create_forbidden_for_contestant_role
    """
    contestant = register_contestant("PRCA-480", "Rider F")

    resp = api.create_judge(
        create_judge_payload(
            card_number="J-48", full_name="Judge F", certification="PRCA_CARD"
        ),
        make_contestant_headers(contestant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    judges = get_success_data(api.list_judges(ADMIN), 200)
    assert judges == [], f"no judge may persist from a forbidden call: {judges}"


def test_vet_report_create_forbidden_for_boxoffice(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint or
    action is rejected with `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4: POST /api/vet-reports is authorized for Veterinarian only.

    Design: Corner/rbac/vet_report_create_forbidden_for_boxoffice
    """
    contestant = register_contestant("PRCA-495", "Rider VB")

    resp = api.create_vet_report(
        create_vet_report_payload(
            subject_type="CONTESTANT",
            contestant_id=contestant["id"],
            findings="x",
            disposition="INJURED_TURNOUT",
            veterinarian_name="Dr. Who",
        ),
        BOX,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    reports = get_success_data(api.list_vet_reports(ADMIN), 200)
    assert reports == [], f"no report may persist from a forbidden call: {reports}"
