"""Breadth: role authority and referential scope."""

import pytest

from test_helpers import (
    NO_ROLE_HEADERS,
    TEST_USERS,
    add_allocation,
    add_project,
    api_client,
    assert_paginated_shape,
    create_payin_payload,
    finalize_underwriting,
    form_fund,
    make_developer_headers,
    make_investor_headers,
    onboard_developer,
    onboard_investor,
    open_subscription,
    read_project,
    setup_committed_project,
    setup_guarantee_scenario,
    setup_project_with_allocation,
    update_project_payload,
    validate_error,
)


def test_the_platform_admin_cannot_commit_a_project():
    """PRD §2.1: "It is not a substitute for the business roles, and in particular
    the platform administration role cannot commit a project to its fund."
    PRD §2.9: "Role authority. The acting role must appear in the endpoint's
    declared role list. Failure is `ERR_FORBIDDEN`, HTTP 403."

    Design: Corner/rbac/platform_admin_cannot_commit_a_project
    """
    from test_helpers import ApiErrorId

    scenario = setup_project_with_allocation()
    project = finalize_underwriting(scenario.project)
    assert project["underwriting_stage"] == "FINAL"

    response = api_client.commit_project(
        project["id"], TEST_USERS["platform_admin_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    assert response.status_code == 403
    assert read_project(project["id"])["status"] == "UNDERWRITING"


def test_an_asset_manager_cannot_finalize_underwriting():
    """PRD §4: "PUT | `/projects/{project_id}` | Edit underwriting inputs, finalize
    or reopen underwriting, or reserve/release an allocation | Underwriter".
    PRD §2.9: "Role authority. The acting role must appear in the endpoint's
    declared role list. Failure is `ERR_FORBIDDEN`, HTTP 403."

    Design: Corner/rbac/asset_manager_cannot_finalize_underwriting
    """
    from test_helpers import ApiErrorId

    scenario = setup_project_with_allocation()
    project = scenario.project

    response = api_client.update_project(
        project["id"],
        update_project_payload(
            project["version"], underwriting_action="FINALIZE"
        ),
        TEST_USERS["asset_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    assert response.status_code == 403
    stored = read_project(project["id"])
    assert stored["underwriting_stage"] == "PRELIMINARY"
    assert stored["final_equity_cents"] is None


def test_a_compliance_officer_cannot_draw_a_guarantee():
    """PRD §3.6: "Guarantee draws are exclusive to the `AssetManager`."
    PRD §2.1: "an `AssetManager` alone may draw against a guarantee."

    Design: Corner/rbac/compliance_officer_cannot_draw_a_guarantee
    """
    from test_helpers import ApiErrorId

    scenario = setup_guarantee_scenario(
        guarantee_type="COMPLETION",
        guaranteed_amount_cents=90000000,
        with_escalated_review=True,
    )

    response = api_client.draw_guarantee(
        scenario.guarantee["id"],
        10000000,
        TEST_USERS["compliance_officer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    assert response.status_code == 403
    from test_helpers import list_project_guarantees

    stored = list_project_guarantees(scenario.project["id"])[0]
    assert stored["drawn_amount_cents"] == 0
    assert stored["status"] == "ACTIVE"


def test_an_investor_cannot_pay_in_against_another_investors_subscription():
    """PRD §2.1: "An `Investor` may reinstate or pay into a subscription only when
    it owns that subscription."
    PRD §2.5: "An entity-backed actor may act only on resources that its own entity
    owns: a `Developer` may act only on its own projects, and an `Investor` may act
    only on its own subscriptions."
    PRD §2.5: "A violation of any of these scope rules is rejected with
    `ERR_FORBIDDEN_SCOPE` and HTTP status 403."

    Design: Corner/rbac/investor_cannot_pay_in_against_another_investors_subscription
    """
    from test_helpers import ApiErrorId

    meridian = onboard_investor()
    northline = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_2",
    )
    fund = form_fund()
    open_subscription(fund, meridian, committed_cents=460000000)
    northline_sub = open_subscription(fund, northline, committed_cents=40000000)

    response = api_client.create_payin(
        northline_sub["id"],
        create_payin_payload(10000000),
        make_investor_headers(meridian["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_SCOPE)
    assert response.status_code == 403
    from test_helpers import read_subscription

    assert read_subscription(northline_sub["id"])["paid_in_cents"] == 0


def test_a_request_with_no_role_header_is_unauthenticated():
    """PRD §2.1: "The authentication failure is reported as `ERR_UNAUTHENTICATED`
    with HTTP status 401. It is raised when `X-User-Role` is absent, when it names
    something that is not one of the seven declared roles, or when it names an
    entity-backed role while `X-User-ID` is absent."

    Design: Corner/rbac/anonymous_caller_is_rejected_by_requiring_the_role_header
    """
    from test_helpers import ApiErrorId

    response = api_client.list_projects(dict(NO_ROLE_HEADERS))

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401


def test_the_anonymous_sentinel_role_is_never_accepted():
    """PRD §2.1: "`Anonymous` is a sentinel, not a usable capacity. It exists
    solely to model a caller that presents no meaningful role. It is never
    permitted on any endpoint".

    Design: Corner/rbac/anonymous_caller_is_rejected_by_requiring_the_role_header
    """
    from test_helpers import ApiErrorId

    response = api_client.list_projects(TEST_USERS["anonymous_headers"])

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401


def test_a_developer_listing_is_filtered_to_its_own_projects():
    """PRD §2.5: "The two collection endpoints that would otherwise fail every
    scoped request — the project listing and the subscription listing — do not
    reject; they filter their results down to the rows the acting entity owns."

    Design: Corner/rbac/developer_actor_reads_only_its_own_projects
    """
    owner = onboard_developer(name="Cedar Ridge Communities")
    stranger = onboard_developer(name="Riverstone Housing Group")
    fund = form_fund()
    mine = add_project(owner["id"], fund["id"], project_name="Riverside Commons")
    theirs = add_project(stranger["id"], fund["id"], project_name="Uptown Yards")

    response = api_client.list_projects(make_developer_headers(owner["id"]))
    rows, meta = assert_paginated_shape(response, expected_total_count=1)

    assert len(rows) == 1
    assert rows[0]["id"] == mine["id"]
    assert rows[0]["id"] != theirs["id"]
