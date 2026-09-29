"""The platform contract: identity headers, the pagination window, the
not-found family, date-range coherence and the role matrix.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    PAGINATION_META_FIELDS,
    assert_all_distinct,
    assert_pagination_meta,
    assert_total_count,
    validate_list,
)
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_ASSESSOR_NOT_FOUND,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_DECISION_NOT_FOUND,
    ERR_DECLARATION_NOT_FOUND,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_PAGINATION,
    ERR_NONCONFORMITY_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ORGANIZATION_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_QUALIFICATION_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SCHEME_NOT_FOUND,
    ERR_SCOPE_NOT_FOUND,
    ERR_TEAM_ASSIGNMENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_WITNESS_SESSION_NOT_FOUND,
)
from test_helpers.constants import (
    APP_PLANNED,
    APP_SUBMITTED,
    APP_TEAM_ASSIGNED,
    ORG_APPLIED,
    PLAN_APPROVED,
    PLAN_DRAFT,
    QUALIFICATION_STATUS_APPLICANT,
    RELATIONSHIP_EMPLOYMENT,
    ROLE_LEAD_ASSESSOR,
    SCHEME_DRAFT,
    SCHEME_PUBLISHED,
    SCHEME_UNDER_REVIEW,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSESSMENT_MANAGER,
    COMPLAINT_OFFICER,
    SCHEME_MANAGER,
    SCHEME_MANAGER_USER_ID,
    headers_with_empty_role,
    headers_with_empty_user_id,
    make_applicant_contact_headers,
    make_decision_panel_member_headers,
    make_lead_assessor_headers,
    make_technical_expert_headers,
)

THREE_SCOPE_LINES = [
    "mass calibration 1 mg - 20 kg",
    "temperature calibration -40 C - 250 C",
    "pressure calibration 0 - 700 bar",
]

UNKNOWN_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
    "55555555-5555-4555-8555-555555555555",
    "66666666-6666-4666-8666-666666666666",
    "77777777-7777-4777-8777-777777777777",
    "88888888-8888-4888-8888-888888888888",
    "99999999-9999-4999-8999-999999999999",
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
)

RULE_SET_FIELDS = (
    "complexity_multiplier",
    "qualification_points_required",
    "critical_nc_close_days",
    "major_nc_close_days",
    "minor_nc_close_days",
)


def test_every_role_may_read_the_scheme_registry(client):
    """All seven identities read the same unfiltered programme record.

    PRD section 2.1: "All seven roles may read the whole registry and all seven
    may set the logical clock."

    Design: Corner/rbac/every_role_may_read_the_scheme_registry
    """
    ctx = fx.new_context(client, "ISO17025-REG")
    fx.with_lead(ctx)
    fx.with_organization(
        ctx,
        legal_name="Northlight Testing AB",
        country_code="SE",
        contact_email="qa@northlight.test",
    )
    scheme_id = ctx["scheme_id"]
    readers = (
        SCHEME_MANAGER,
        ASSESSMENT_MANAGER,
        COMPLAINT_OFFICER,
        make_lead_assessor_headers(ctx["lead_id"]),
        make_technical_expert_headers(ctx["lead_id"]),
        make_decision_panel_member_headers(ctx["lead_id"]),
        make_applicant_contact_headers(ctx["org_id"]),
    )
    assert len(readers) == 7

    reads = [
        validate_success(client.get_scheme(scheme_id, headers), 200)
        for headers in readers
    ]

    for scheme in reads:
        assert scheme["id"] == scheme_id
        assert scheme["status"] == SCHEME_PUBLISHED
        assert scheme["rule_revision"] == 1
        assert scheme["published_at"] is not None
        for field in RULE_SET_FIELDS:
            assert scheme[field] is not None, f"{field} is masked for a reader"
        assert scheme == reads[0], "No read is filtered by role"
    for headers in readers:
        assert_total_count(client.list_schemes(headers), 1)


def test_listing_schemes_without_identity_headers_is_rejected(client):
    """An absent or empty identity header is refused before anything else is
    considered.

    PRD section 2.1: "Every request to every endpoint — reads included — must
    carry two headers: `X-User-ID` and `X-User-Role`. If either header is
    absent, or present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the server
    performs, ahead of any parsing of the body or resolution of any path
    identifier."

    Design: Corner/errors/list_schemes_unauthenticated_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    fx.create_published_scheme(client, "ISO17025-AUT")

    response = client.list_schemes(headers_with_empty_role(SCHEME_MANAGER_USER_ID))

    validate_error(response, ERR_UNAUTHENTICATED, 401)
    body = response.json()
    assert "items" not in body["data"]
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], f"An error envelope carries no {field}"
    no_user_id = client.list_schemes(headers_with_empty_user_id(ROLE_LEAD_ASSESSOR))
    validate_error(no_user_id, ERR_UNAUTHENTICATED, 401)
    assert "items" not in no_user_id.json()["data"]
    assert_total_count(client.list_schemes(SCHEME_MANAGER), 1)
    with_bad_pagination = client.list_schemes(
        headers_with_empty_role(SCHEME_MANAGER_USER_ID), {"limit": 0}
    )
    validate_error(with_bad_pagination, ERR_UNAUTHENTICATED, 401)


def test_pagination_window_outside_the_declared_bounds_is_rejected(client):
    """The window is validated against its declared range, and the omitted
    window falls back to the declared defaults.

    PRD section 2.3: "`limit` defaults to 10 when omitted, must be an integer,
    and must be at least 1 and at most 100. `offset` defaults to 0 when
    omitted, must be an integer, and must be at least 0; it has no upper bound.
    A `limit` outside the 1-to-100 range, or an `offset` below 0, or a
    non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    Design: Corner/errors/list_schemes_with_limit_outside_the_declared_window_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    fx.create_published_scheme(client, "ISO17025-PAG")

    response = client.list_schemes(SCHEME_MANAGER, {"limit": 101})

    validate_error(response, ERR_INVALID_PAGINATION, 400)
    validate_error(
        client.list_schemes(SCHEME_MANAGER, {"limit": 0}), ERR_INVALID_PAGINATION, 400
    )
    validate_error(
        client.list_schemes(SCHEME_MANAGER, {"offset": -1}), ERR_INVALID_PAGINATION, 400
    )
    rows, meta = validate_list(
        client.list_schemes(SCHEME_MANAGER, {"limit": 100, "offset": 0})
    )
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1, has_more=False)
    assert len(rows) == 1
    _, defaults = validate_list(client.list_schemes(SCHEME_MANAGER))
    assert defaults["limit"] == 10
    assert defaults["offset"] == 0


def test_every_resource_route_with_an_unknown_identifier_is_not_found(client):
    """Thirteen resource types each report their own not-found error.

    PRD section 2.9: "Each identifier that fails to resolve to a live row
    produces the not-found error of its own resource type, at HTTP 404:
    `ERR_SCHEME_NOT_FOUND`, `ERR_ASSESSOR_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`,
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_WITNESS_SESSION_NOT_FOUND`, `ERR_NONCONFORMITY_NOT_FOUND`,
    `ERR_DECISION_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND` and
    `ERR_COMPLAINT_NOT_FOUND`."

    Design: Corner/errors/every_resource_route_with_an_unknown_uuid_not_found
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    routes = (
        (client.get_scheme, ERR_SCHEME_NOT_FOUND),
        (client.get_assessor, ERR_ASSESSOR_NOT_FOUND),
        (client.get_qualification, ERR_QUALIFICATION_NOT_FOUND),
        (client.get_declaration, ERR_DECLARATION_NOT_FOUND),
        (client.get_organization, ERR_ORGANIZATION_NOT_FOUND),
        (client.get_application, ERR_APPLICATION_NOT_FOUND),
        (client.get_team_assignment, ERR_TEAM_ASSIGNMENT_NOT_FOUND),
        (client.get_plan, ERR_PLAN_NOT_FOUND),
        (client.get_witness_session, ERR_WITNESS_SESSION_NOT_FOUND),
        (client.get_nonconformity, ERR_NONCONFORMITY_NOT_FOUND),
        (client.get_decision, ERR_DECISION_NOT_FOUND),
        (client.get_scope, ERR_SCOPE_NOT_FOUND),
        (client.get_complaint, ERR_COMPLAINT_NOT_FOUND),
    )
    assert len(routes) == len(UNKNOWN_IDS) == 13

    responses = [
        (read(unknown, SCHEME_MANAGER), expected_error)
        for (read, expected_error), unknown in zip(routes, UNKNOWN_IDS)
    ]

    observed = []
    for response, expected_error in responses:
        validate_error(response, expected_error, 404)
        payload = response.json()["data"]
        assert set(payload) == {"error_id", "message"}, (
            "A 404 body carries no entity payload"
        )
        assert isinstance(payload["message"], str) and payload["message"]
        observed.append(payload["error_id"])
    assert_all_distinct(observed, "not-found error ids")


def test_assessment_manager_cannot_drive_the_scheme_lifecycle(client):
    """Rule development belongs to one role, and the role check runs before the
    transition check.

    PRD section 2.1: "A value of `X-User-Role` that is not one of those seven
    strings, or that is one of them but is not among the roles authorised for
    the endpoint being called, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
    403). The authorised roles for each endpoint are listed in the table in
    §4." and section 2.9: "Role validity and endpoint authorisation
    (`ERR_ROLE_NOT_PERMITTED`), and, for the three owner-guarded operations,
    applicant-organization ownership (`ERR_NOT_RESOURCE_OWNER`). These two
    share a precedence rank."

    Design: Corner/rbac/assessment_manager_cannot_publish_a_scheme_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_scheme(client, "ISO17025-RBS")
    assert scheme["status"] == SCHEME_DRAFT

    response = client.set_scheme_status(
        scheme["id"], f.scheme_status_payload(SCHEME_UNDER_REVIEW), ASSESSMENT_MANAGER
    )

    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
    stored = validate_success(client.get_scheme(scheme["id"], SCHEME_MANAGER), 200)
    assert stored["status"] == SCHEME_DRAFT
    assert stored["rule_revision"] == 1
    assert stored["published_at"] is None
    illegal_transition = client.set_scheme_status(
        scheme["id"], f.scheme_status_payload(SCHEME_PUBLISHED), ASSESSMENT_MANAGER
    )
    # The role check outranks the transition check: PUBLISHED is not a
    # declared successor of DRAFT, yet the role verdict is the one returned.
    validate_error(illegal_transition, ERR_ROLE_NOT_PERMITTED, 403)
    permitted = validate_success(
        client.set_scheme_status(
            scheme["id"], f.scheme_status_payload(SCHEME_UNDER_REVIEW), SCHEME_MANAGER
        ),
        200,
    )
    assert permitted["status"] == SCHEME_UNDER_REVIEW


def test_applicant_contact_cannot_register_assessors(client):
    """The applicant's own contact may not recruit the body's assessors, and
    the role check outranks the payload check.

    PRD section 2.9: "Role validity and endpoint authorisation
    (`ERR_ROLE_NOT_PERMITTED`), and, for the three owner-guarded operations,
    applicant-organization ownership (`ERR_NOT_RESOURCE_OWNER`). These two
    share a precedence rank." and "Request-shape validity: on every write, the
    body must be a JSON object, every required input must be present, every
    enum-typed value must be a member of its declared set, every count field
    must be non-negative, and every monetary or points field must be numeric —
    otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/rbac/applicant_contact_cannot_register_assessors_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    organization = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )
    applicant = make_applicant_contact_headers(organization["id"])

    response = client.create_assessor(
        f.assessor_payload("Lena Ahlgren", "lena.ahlgren@ab.test"), applicant
    )

    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
    malformed = client.create_assessor({"full_name": "Lena Ahlgren"}, applicant)
    validate_error(malformed, ERR_ROLE_NOT_PERMITTED, 403)
    assert_total_count(client.list_assessors(ASSESSMENT_MANAGER), 0)
    created = validate_success(
        client.create_assessor(
            f.assessor_payload(
                "Lena Ahlgren", "lena.ahlgren@ab.test", annual_witness_capacity_days=10
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert created["qualification_status"] == QUALIFICATION_STATUS_APPLICANT
    assert created["annual_witness_capacity_days"] == 10


def test_complaint_officer_cannot_approve_or_return_an_assessment_plan(client):
    """The case-handling role is outside the assessment function entirely.

    PRD section 2.1: "A `ComplaintOfficer` handles complaints and appeals
    independently of the assessment and decision functions, and discharges the
    body's international mutual-recognition notification obligations."

    Design: Corner/rbac/complaint_officer_cannot_approve_an_assessment_plan_rejected
    """
    ctx = fx.scenario_team_assigned(
        client, "ISO17025-RBP", requested_scope_lines=THREE_SCOPE_LINES
    )
    plan = fx.create_plan(client, ctx["app_id"], 3, 2)
    assert plan["status"] == PLAN_DRAFT

    response = client.approve_plan(plan["id"], COMPLAINT_OFFICER)

    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
    returned = client.return_plan_to_draft(
        plan["id"],
        f.return_to_draft_payload("The day budget needs revisiting."),
        COMPLAINT_OFFICER,
    )
    validate_error(returned, ERR_ROLE_NOT_PERMITTED, 403)
    stored = validate_success(client.get_plan(plan["id"], ASSESSMENT_MANAGER), 200)
    assert stored["status"] == PLAN_DRAFT
    assert stored["approved_at"] is None
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["planned_effort_days"] is None
    approved = validate_success(client.approve_plan(plan["id"], ASSESSMENT_MANAGER), 200)
    assert approved["status"] == PLAN_APPROVED
    planned = fx.read_application(client, ctx["app_id"])
    assert planned["status"] == APP_PLANNED
    assert planned["planned_effort_days"] == 8


def test_inverted_date_ranges_on_a_plan_and_a_declaration_are_rejected(client):
    """Date coherence is checked on both guarded endpoints, and it outranks the
    concurrency token.

    PRD section 2.9: "Date-range coherence (`ERR_INVALID_DATE_RANGE`, HTTP
    422): a plan's `planned_end` must be on or after its `planned_start`; a
    witnessing slot's `ends_at` must be strictly after its `starts_at`; a
    declaration's `ended_on`, when supplied, must be on or after its
    `started_on`. Those three endpoints — plan creation, witness-session
    scheduling and declaration filing — are the only ones this check guards."

    Design: Corner/errors/assessment_plan_and_declaration_with_an_inverted_date_range_rejected
    """
    ctx = fx.scenario_team_assigned(
        client, "ISO17025-DTR", requested_scope_lines=THREE_SCOPE_LINES
    )
    current_version = fx.read_application_version(client, ctx["app_id"])

    response = client.create_plan(
        ctx["app_id"],
        f.plan_payload(
            current_version,
            3,
            2,
            planned_start="2026-09-18",
            planned_end="2026-09-07",
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_INVALID_DATE_RANGE, 422)
    declaration = client.create_declaration(
        ctx["lead_id"],
        f.declaration_payload(
            ctx["org_id"],
            RELATIONSHIP_EMPLOYMENT,
            "2026-03-01",
            ended_on="2026-02-01",
            detail="Quality manager on a fixed-term contract.",
        ),
        ASSESSMENT_MANAGER,
    )
    validate_error(declaration, ERR_INVALID_DATE_RANGE, 422)
    assert_total_count(
        client.list_plans(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 0
    )
    assert_total_count(
        client.list_declarations(ASSESSMENT_MANAGER, {"assessor_id": ctx["lead_id"]}), 0
    )
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["planned_effort_days"] is None
    assert application["version"] == current_version, "Neither rejection mutated a row"
    with_stale_token = client.create_plan(
        ctx["app_id"],
        f.plan_payload(
            current_version - 1,
            3,
            2,
            planned_start="2026-09-18",
            planned_end="2026-09-07",
        ),
        ASSESSMENT_MANAGER,
    )
    # Date coherence sits at rank 4 and the version token at rank 7.
    validate_error(with_stale_token, ERR_INVALID_DATE_RANGE, 422)


def test_applicant_contact_opening_a_cycle_for_another_organization_is_rejected(client):
    """Ownership is compared before any body-supplied reference is resolved.

    PRD section 2.1: "An `ApplicantContact` acting on data that belongs to a
    different applicant organization is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403). This ownership check guards exactly three operations: opening
    an assessment cycle, submitting a corrective-action response against a
    finding, and filing a complaint or appeal." and section 2.9: "Foreign keys
    supplied **in the request body** are resolved only after every path
    identifier has resolved, and among themselves they are resolved in the
    order the fields are declared for that endpoint."

    Design: Corner/errors/applicant_contact_opening_a_cycle_for_another_organization_rejected
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(client, "ISO17025-OWN")
    own = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )
    other = fx.register_organization(
        client, "Selvik Metrology AS", "NO", "qa@selvik.test"
    )
    contact = make_applicant_contact_headers(own["id"])

    response = client.create_application(
        f.application_payload(other["id"], scheme["id"], requested_scope_lines=THREE_SCOPE_LINES),
        contact,
    )

    validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)
    assert_total_count(
        client.list_applications(ASSESSMENT_MANAGER, {"organization_id": other["id"]}), 0
    )
    unknown_scheme = client.create_application(
        f.application_payload(
            other["id"], UNKNOWN_IDS[0], requested_scope_lines=THREE_SCOPE_LINES
        ),
        contact,
    )
    # Ownership at rank 2 outranks foreign-key resolution at rank 6.
    validate_error(unknown_scheme, ERR_NOT_RESOURCE_OWNER, 403)
    accepted = validate_success(
        client.create_application(
            f.application_payload(
                own["id"], scheme["id"], requested_scope_lines=THREE_SCOPE_LINES
            ),
            contact,
        ),
        201,
    )
    assert accepted["organization_id"] == own["id"]
    assert accepted["status"] == APP_SUBMITTED
    stored_other = validate_success(
        client.get_organization(other["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_other["status"] == ORG_APPLIED
    assert_total_count(
        client.list_applications(ASSESSMENT_MANAGER, {"organization_id": other["id"]}), 0
    )
