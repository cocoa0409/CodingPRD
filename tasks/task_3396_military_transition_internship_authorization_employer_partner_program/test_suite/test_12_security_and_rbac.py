"""Auth context, role permission, entity-backed ownership, and OCC on the
opening version at match creation."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, factories, fixtures, make_employer_rep_headers, make_service_member_headers
from test_helpers.test_users import (
    PROGRAM_OFFICE_HEADERS,
    make_unit_commander_headers,
)


def test_missing_auth_headers_return_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role name outside
    this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_return_400
    """
    sentinel = fixtures.create_employer(api, legal_name="Sentinel Corp", industry_code="DEF")
    assert sentinel["id"], "control: the server accepts well-formed authenticated calls"

    resp = api.create_installation(factories.create_installation_payload(name="No Headers"), None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_rbac_exclusive_ops_unauthorized(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to call the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.7 runs the role-permission check (rung 3) before any state check, so the
    UnitCommander's adjudication attempt is refused even though the application is
    not UNDER_APPEAL.

    Design: Corner/rbac/rbac_exclusive_ops_unauthorized
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    employer = fixtures.create_employer(api)

    member_deciding = api.commander_decision(
        w.application["id"], factories.commander_decision_payload("APPROVE"),
        make_service_member_headers(w.member["id"]),
    )
    validate_error(member_deciding, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    rep_authorizing = api.authorize_employer(employer["id"], make_employer_rep_headers(employer["id"]))
    validate_error(rep_authorizing, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    office_posting = api.create_opening(
        factories.create_opening_payload(employer["id"], title="Wrong Role"), PROGRAM_OFFICE_HEADERS
    )
    validate_error(office_posting, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    commander_adjudicating = api.adjudicate_appeal(
        w.application["id"], factories.adjudicate_payload("UPHELD", "wrong role"),
        make_unit_commander_headers("cmd-1"),
    )
    validate_error(commander_adjudicating, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    assert fixtures.get_application(api, w.application["id"])["status"] == "SUBMITTED"
    assert fixtures.get_employer(api, employer["id"])["authorization_status"] == "PENDING_AUTHORIZATION"
    data, meta = validate_paginated(api.list_openings(PROGRAM_OFFICE_HEADERS, params={"employer_id": employer["id"]}))
    assert data == [] and meta["total_count"] == 0


def test_entity_backed_ownership_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `ServiceMember`, `X-User-ID` is the `id` of
    the acting ServiceMember; ownership checks on any resource that references a
    ServiceMember compare the resource's foreign-key field (such as
    `service_member_id` on an application) to `X-User-ID`."
    PRD §2.7: "`ERR_FORBIDDEN_OWNERSHIP` (HTTP 403): the member's `X-User-ID` must
    equal the application's `service_member_id` on application submission and
    appeal; the employer representative's `X-User-ID` must equal the owning
    employer of the opening or match being touched on opening creation, opening
    close, match proposal, plan submission, employer-side termination, supervision
    report filing, wage record posting, and conversion recording."

    Design: Corner/rbac/entity_backed_ownership_forbidden
    """
    inst = fixtures.create_installation(api)
    member_a = fixtures.create_member(api, inst["id"], full_name="Alice Vega")
    member_b = fixtures.create_member(api, inst["id"], full_name="Ben Cole", service_branch="NAVY", pay_grade="E6")
    member_c = fixtures.create_member(api, inst["id"], full_name="Cara Diaz", service_branch="MARINES", pay_grade="E4")
    app_a = fixtures.submit_application(api, member_a["id"])
    fixtures.deny_application(api, app_a["id"], reason="Manning")
    app_c = fixtures.approve_application(api, fixtures.submit_application(api, member_c["id"])["id"])

    employer_a = fixtures.create_authorized_employer(api)
    employer_b = fixtures.create_employer(api, legal_name="Beacon Retail Group", industry_code="RET")
    opening_a = fixtures.create_opening(api, employer_a["id"])

    stranger_appeal = api.appeal_application(
        app_a["id"], factories.appeal_payload("not my application"),
        make_service_member_headers(member_b["id"]),
    )
    validate_error(stranger_appeal, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    foreign_match = api.create_match(
        factories.create_match_payload(
            app_c["id"], opening_a["id"], opening_a["version"], "2026-10-01", "2026-10-31"
        ),
        make_employer_rep_headers(employer_b["id"]),
    )
    validate_error(foreign_match, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_occ_stale_opening_version_on_match_create(api):
    """PRD §2.6: "Proposing an internship match requires
    `expected_employer_opening_version`, carrying the client's last observed
    `version` of the target EmployerOpening. A mismatch with the opening's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the client's view of
    remaining capacity is stale, and it must re-read the opening and retry with the
    fresh version."

    Design: Corner/cross_cutting_layers/occ_stale_opening_version_on_match_create
    """
    w = fixtures.setup_members_with_approved_applications(api, 2)
    eo = fixtures.setup_employer_with_opening(api, capacity=2)
    employer, opening = eo.employer, eo.opening
    observed_version = opening["version"]

    first = api.create_match(
        factories.create_match_payload(
            w.applications[0]["id"], opening["id"], observed_version, "2026-10-01", "2026-10-31"
        ),
        make_employer_rep_headers(employer["id"]),
    )
    validate_success(first, 201)
    assert fixtures.get_opening(api, opening["id"])["version"] == observed_version + 1

    stale = api.create_match(
        factories.create_match_payload(
            w.applications[1]["id"], opening["id"], observed_version, "2026-11-15", "2026-12-15"
        ),
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    data, meta = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"internship_application_id": w.applications[1]["id"]})
    )
    assert data == [], "the stale write persists no match"

    fresh_version = fixtures.get_opening(api, opening["id"])["version"]
    retry = api.create_match(
        factories.create_match_payload(
            w.applications[1]["id"], opening["id"], fresh_version, "2026-11-15", "2026-12-15"
        ),
        make_employer_rep_headers(employer["id"]),
    )
    validate_success(retry, 201)
