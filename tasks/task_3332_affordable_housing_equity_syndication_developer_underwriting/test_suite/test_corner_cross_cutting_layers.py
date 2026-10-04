"""Breadth: revision bands, derived-field reconciliation and suspension fallout."""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_capital_call_payload,
    create_subscription_payload,
    form_fund,
    get_success_data,
    list_project_capital_calls,
    make_investor_headers,
    onboard_investor,
    open_review,
    open_subscription,
    read_developer,
    read_fund,
    read_project,
    resolve_review,
    schedule_capital_call,
    setup_canonical_scenario,
    setup_committed_project,
    setup_defaulted_subscription,
    update_project_payload,
    validate_error,
)


def test_a_subscription_create_on_a_stale_fund_version_is_precondition_failed():
    """PRD §2.8: "Creating a subscription against a fund is a write that must carry
    `expected_fund_version`, holding the client's last observed `version` of the
    target `SyndicationFund`. If the fund's version has advanced since the client
    last read it, the create is rejected with `ERR_STALE_VERSION` and HTTP status
    412."

    Design: Corner/cross_cutting_layers/stale_fund_version_on_subscription_create_returns_precondition_failed
    """
    from test_helpers import ApiErrorId

    scenario = setup_canonical_scenario(with_subscription=False, with_project=False)
    fund = scenario.fund
    stale_version = fund["version"]

    open_subscription(fund, scenario.investor, committed_cents=200000000)
    assert read_fund(fund["id"])["version"] > stale_version

    other = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_2",
    )
    response = api_client.create_subscription(
        fund["id"],
        create_subscription_payload(
            investor_id=other["id"],
            expected_fund_version=stale_version,
            committed_cents=200000000,
            payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
        ),
        make_investor_headers(other["id"]),
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412
    fund_after = read_fund(fund["id"])
    assert fund_after["subscribed_equity_cents"] == 200000000
    assert fund_after["subscription_count"] == 1


def test_an_underwriting_edit_on_a_stale_project_version_is_precondition_failed():
    """PRD §2.8: "Editing a project's underwriting inputs must carry
    `expected_project_version`, holding the client's last observed `version` of the
    target `Project`. A mismatch is rejected with `ERR_STALE_VERSION` and HTTP
    status 412."

    Design: Corner/cross_cutting_layers/stale_project_version_on_underwriting_edit_returns_precondition_failed
    """
    from test_helpers import ApiErrorId

    scenario = setup_canonical_scenario(with_subscription=False, with_project=True)
    project = scenario.project
    stale_version = project["version"]

    first = get_success_data(
        api_client.update_project(
            project["id"],
            update_project_payload(stale_version, construction_loan_cents=720000000),
            TEST_USERS["underwriter_headers"],
        )
    )
    assert first["construction_loan_cents"] == 720000000
    assert first["version"] > stale_version

    response = api_client.update_project(
        project["id"],
        update_project_payload(stale_version, construction_loan_cents=800000000),
        TEST_USERS["underwriter_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412
    stored = read_project(project["id"])
    assert stored["construction_loan_cents"] == 720000000
    assert stored["preliminary_equity_cents"] == 471858755


def test_a_capital_call_create_on_a_stale_project_version_is_precondition_failed():
    """PRD §2.8: "Scheduling a new capital call against a project must also carry
    `expected_project_version`. A mismatch is rejected with `ERR_STALE_VERSION` and
    HTTP status 412."

    Design: Corner/cross_cutting_layers/stale_project_version_on_capital_call_create_returns_precondition_failed
    """
    from test_helpers import ApiErrorId

    scenario = setup_canonical_scenario(with_subscription=False, with_project=True)
    project = scenario.project
    stale_version = project["version"]

    first = schedule_capital_call(project["id"], "CONSTRUCTION_START")
    assert read_project(project["id"])["version"] > stale_version

    response = api_client.create_capital_call(
        project["id"],
        create_capital_call_payload(
            milestone="CONSTRUCTION_50PCT",
            expected_project_version=stale_version,
            scheduled_date="2026-11-15T00:00:00Z",
            due_date="2026-12-15T00:00:00Z",
        ),
        TEST_USERS["asset_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert response.status_code == 412
    calls = list_project_capital_calls(project["id"])
    assert len(calls) == 1
    assert calls[0]["id"] == first["id"]
    assert calls[0]["status"] == "SCHEDULED"


def test_an_escalated_review_recomputes_the_fund_posture_without_a_fund_write():
    """PRD §2.10: "The platform's two most consequential values are never set
    directly by a client: a fund's `posture` and a developer's `status` are both
    derived, and both are recomputed whenever any input to their derivation
    changes."
    PRD §3.7: "Resolving a review into `ESCALATED` stamps `escalated_at` with the
    logical clock, moves the owning project to `DISTRESSED` because an escalated
    review is sufficient on its own, recomputes the owning developer's status, and
    recomputes the owning fund's posture."

    Design: Corner/cross_cutting_layers/derived_posture_field_recomputes_on_a_write_that_never_touches_the_fund
    """
    scenario = setup_committed_project()
    fund_id = scenario.fund["id"]
    assert read_fund(fund_id)["posture"] == "OPEN"

    review = open_review(scenario.project["id"], review_period_index=1)
    resolve_review(
        review["id"],
        outcome="ESCALATED",
        headers=TEST_USERS["compliance_officer_headers"],
    )

    assert read_project(scenario.project["id"])["status"] == "DISTRESSED"
    assert read_fund(fund_id)["posture"] == "WATCH"
    assert read_developer(scenario.developer["id"])["status"] == "WATCH"


def test_a_suspended_investor_cannot_open_a_subscription_in_another_fund():
    """PRD §3.2: "A subscription attempted on behalf of an investor whose `status`
    is `SUSPENDED` is rejected with `ERR_INVESTOR_SUSPENDED`."
    PRD §3.2: "It moves from `ACTIVE` to `SUSPENDED` as soon as at least one of its
    subscriptions has reached `DEFAULTED`."

    Design: Corner/cross_cutting_layers/suspended_investor_is_blocked_from_further_subscriptions
    """
    from test_helpers import ApiErrorId

    scenario = setup_defaulted_subscription()
    assert scenario.investor["status"] == "SUSPENDED"

    other_fund = form_fund(
        fund_name="ECP Housing Fund V",
        target_equity_cents=400000000,
        price_per_credit_dollar=0.9050,
        target_yield_pct=0.065,
        subscription_close_date="2027-06-30T00:00:00Z",
    )
    response = api_client.create_subscription(
        other_fund["id"],
        create_subscription_payload(
            investor_id=scenario.investor["id"],
            expected_fund_version=other_fund["version"],
            committed_cents=50000000,
            payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
        ),
        make_investor_headers(scenario.investor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVESTOR_SUSPENDED)
    assert response.status_code == 403
    assert read_fund(other_fund["id"])["subscribed_equity_cents"] == 0
