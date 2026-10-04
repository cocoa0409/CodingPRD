"""Role-based access control boundaries."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_advisor, create_territory, create_branch_payload,
    create_validated_advisor, create_site_approved_branch,
    create_period, set_clock, post_production, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_principal_headers"]


def test_advisor_cannot_create_branch():
    """PRD §2.1: "Once authenticated, a role that attempts an operation
    outside its grant is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/advisor_cannot_create_branch
    """
    advisor = create_advisor()
    territory = create_territory()

    validate_error(
        api_client.create_branch(
            create_branch_payload(territory["id"]),
            make_advisor_headers(advisor["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_advisor_cannot_evaluate_own_milestone():
    """PRD §2.1: "Once authenticated, a role that attempts an operation
    outside its grant is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.1: "A `HomeOfficeAdmin` then evaluates the pending milestone,
    supplying a `window_end`."

    Design: Corner/rbac/advisor_cannot_evaluate_own_milestone
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 100, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )

    validate_error(
        api_client.evaluate_milestone(
            program["id"],
            {"window_end": "2026-04-05T00:00:00Z"},
            make_advisor_headers(advisor["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert get_success_data(
        api_client.get_training_program(program["id"], ADMIN)
    )["status"] == "MILESTONE_PENDING"


def test_compliance_cannot_finalize_period():
    """PRD §2.1: "Once authenticated, a role that attempts an operation
    outside its grant is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/compliance_cannot_finalize_period
    """
    territory = create_territory()
    from test_helpers import create_branch
    branch, _ = create_branch(territory["id"])
    period = create_period(branch["id"])

    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(period["id"], ADMIN))

    validate_error(
        api_client.finalize_period(period["id"], COMPLIANCE),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert get_success_data(
        api_client.get_financial_period(period["id"], ADMIN)
    )["status"] == "CLOSED"


def test_advisor_cannot_retire_other_advisor():
    """PRD §2.1: "When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of
    the acting `Advisor` record; ownership checks on any resource that
    references an advisor (retirement declarations, milestone submissions,
    solicitation requests, goodwill negotiations, door-knock contacts) compare
    the resource's advisor foreign key to `X-User-ID`."

    Design: Corner/rbac/advisor_cannot_retire_other_advisor
    """
    branch, territory = create_site_approved_branch()
    advisor_a = create_validated_advisor()
    validate_success(
        api_client.assign_branch(advisor_a["id"], {"branch_id": branch["id"]}, ADMIN)
    )
    advisor_b = create_advisor()

    validate_error(
        api_client.declare_retirement(
            advisor_a["id"], make_advisor_headers(advisor_b["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert get_success_data(
        api_client.get_advisor(advisor_a["id"], ADMIN)
    )["status"] == "PRACTICING"
