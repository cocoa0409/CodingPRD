"""Breadth: creation, retrieval, defaults and listings on the core resources."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_allocation,
    add_project,
    api_client,
    assert_developer,
    assert_fund,
    assert_paginated_shape,
    assert_project,
    assert_same_instant,
    create_fund_payload,
    create_subscription_payload,
    form_fund,
    get_success_data,
    make_investor_headers,
    onboard_developer,
    onboard_investor,
    open_subscription,
    read_developer,
    read_fund,
    read_project,
    schedule_capital_call,
    validate_error,
    validate_success,
)

_AGENCY = "Oregon Housing and Community Services"


def test_the_logical_clock_starts_at_its_pinned_default_instant():
    """PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and it continues to read that value until an operator
    advances it."
    PRD §3.5: "The logical clock must be at or after the call's `scheduled_date`,
    else the request is rejected with `ERR_CALL_NOT_DUE`."

    No clock call is made, so a call scheduled for 2026-10-01 is still not due.

    Design: Corner/entities/logical_clock_starts_at_the_pinned_default_instant
    """
    developer = onboard_developer()
    investor = onboard_investor()
    fund = form_fund()
    project = add_project(developer["id"], fund["id"])
    call = schedule_capital_call(project["id"], "CONSTRUCTION_START")

    response = api_client.issue_capital_call(
        call["id"], TEST_USERS["asset_manager_headers"]
    )

    from test_helpers import ApiErrorId

    validate_error(response, ApiErrorId.ERR_CALL_NOT_DUE)
    assert response.status_code == 422
    from test_helpers import find_capital_call

    assert find_capital_call(project["id"], call["id"])["status"] == "SCHEDULED"


def test_developer_create_returns_a_derived_status_and_zero_counters():
    """PRD §3.1: "On onboarding, `guarantee_exposure_cents` and
    `active_project_count` both start at zero, and `status` is derived rather than
    accepted."
    PRD §3.1: "A `PlatformAdmin` onboards a sponsor by supplying `name`,
    `developer_type`, `sponsor_experience_months`, `projects_completed`,
    `net_worth_cents`, and `liquid_assets_cents`."

    Design: Corner/entities/developer_create_returns_derived_status_and_zero_counters
    """
    response = api_client.create_developer(
        {
            "name": "Cedar Ridge Communities",
            "developer_type": "FOR_PROFIT",
            "sponsor_experience_months": 96,
            "projects_completed": 4,
            "net_worth_cents": 2000000000,
            "liquid_assets_cents": 30000000,
        },
        TEST_USERS["platform_admin_headers"],
    )

    developer = validate_success(response, expected_status=201)
    assert_developer(developer)
    assert developer["developer_type"] == "FOR_PROFIT"
    assert developer["net_worth_cents"] == 2000000000
    assert developer["status"] == "ELIGIBLE"
    assert developer["guarantee_exposure_cents"] == 0
    assert developer["active_project_count"] == 0
    assert response.json()["meta"].get("api_request_id")


def test_fund_create_omitting_the_close_threshold_defaults_to_zero_point_eight_five():
    """PRD §3.3: "The `close_threshold_pct` expresses the fraction of the target
    equity that must be subscribed before the fund may close, and when it is
    omitted it defaults to 0.85."
    PRD §3.3: "A newly formed fund begins at `FORMING`, with `posture` `OPEN` and
    with `funded_equity_cents`, `subscribed_equity_cents`, and `subscription_count`
    all at zero."

    Design: Corner/entities/fund_create_omitting_close_threshold_defaults_to_eighty_five_percent
    """
    payload = create_fund_payload(omit_close_threshold=True)
    assert "close_threshold_pct" not in payload

    response = api_client.create_fund(payload, TEST_USERS["underwriter_headers"])
    fund = validate_success(response, expected_status=201)

    assert_fund(fund)
    assert fund["close_threshold_pct"] == pytest.approx(0.85, abs=1e-9)
    assert fund["price_per_credit_dollar"] == pytest.approx(0.9123, abs=1e-9)
    assert fund["status"] == "FORMING"
    assert fund["posture"] == "OPEN"
    assert fund["subscribed_equity_cents"] == 0
    assert fund["funded_equity_cents"] == 0
    assert fund["subscription_count"] == 0


def test_get_project_with_an_unknown_id_returns_project_not_found():
    """PRD §2.5: "A missing developer is reported as `ERR_DEVELOPER_NOT_FOUND`, a
    missing fund as `ERR_FUND_NOT_FOUND`, a missing project as
    `ERR_PROJECT_NOT_FOUND`".
    PRD §2.5: "All of these carry HTTP status 404."

    Design: Corner/entities/project_get_with_an_unknown_id_returns_project_not_found
    """
    from test_helpers import ApiErrorId

    response = api_client.get_project(
        NON_EXISTENT_UUID, TEST_USERS["underwriter_headers"]
    )

    body = validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"
    assert body.get("error_id") == ApiErrorId.ERR_PROJECT_NOT_FOUND.value
    assert body.get("message")


def test_subscription_create_without_committed_cents_returns_invalid_request():
    """PRD §3.2: "A subscription is created with `investor_id`, `committed_cents`,
    `payin_schedule`, and `expected_fund_version`."
    PRD §2.9: "Request shape. Every required input must be present, every enum
    input must be a declared member, every numeric input must be non-negative".
    PRD §2.9: "Failure is `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/subscription_create_missing_committed_cents_returns_invalid_request
    """
    from test_helpers import ApiErrorId

    investor = onboard_investor()
    fund = form_fund()
    payload = create_subscription_payload(
        investor_id=investor["id"],
        expected_fund_version=fund["version"],
        payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
    )
    payload.pop("committed_cents")

    response = api_client.create_subscription(
        fund["id"], payload, make_investor_headers(investor["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400
    fund_after = read_fund(fund["id"])
    assert fund_after["subscribed_equity_cents"] == 0
    assert fund_after["subscription_count"] == 0


def test_an_allocation_addressed_through_another_projects_path_is_not_found():
    """PRD §2.5: "An allocation that exists but belongs to a different project is
    likewise reported as `ERR_ALLOCATION_NOT_FOUND`, because an allocation is only
    addressable within its own project."

    Design: Corner/entities/allocation_create_under_the_wrong_project_returns_allocation_not_found
    """
    from test_helpers import ApiErrorId

    developer = onboard_developer()
    fund = form_fund()
    project_a = add_project(developer["id"], fund["id"], project_name="Riverside Commons")
    project_b = add_project(developer["id"], fund["id"], project_name="Juniper Flats")
    allocation = add_allocation(project_a["id"])

    response = api_client.rescind_allocation(
        project_b["id"], allocation["id"], TEST_USERS["asset_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ALLOCATION_NOT_FOUND)
    assert response.status_code == 404
    from test_helpers import list_project_allocations

    assert list_project_allocations(project_a["id"])[0]["status"] == "AWARDED"


def test_project_create_derives_the_initial_pipeline_state_and_figures():
    """PRD §3.4: "A new project starts at `UNDERWRITING` with `underwriting_stage`
    `PRELIMINARY`, and creation immediately computes `preliminary_equity_cents` and
    `underwritten_equity_cents`, and derives `dscr`, `operating_deficit_cents`, and
    `underwritten_gap_cents`."

    Design: Corner/entities/project_create_ignores_an_input_supplied_status_field
    """
    developer = onboard_developer()
    fund = form_fund()

    response = api_client.create_project(
        {
            "developer_id": developer["id"],
            "fund_id": fund["id"],
            "project_name": "Riverside Commons",
            "state_code": "OR",
            "total_credit_dollars_cents": 912345678,
            "construction_budget_cents": 1234567890,
            "construction_loan_cents": 700000000,
            "operating_pro_forma_noi_cents": 72000000,
            "debt_service_cents": 60000000,
            "market_study_absorption_score": 0.83,
            "sponsor_experience_months": 96,
            "placed_in_service_deadline": "2028-12-31T00:00:00Z",
            "compliance_period_months": 180,
        },
        TEST_USERS["underwriter_headers"],
    )
    project = validate_success(response, expected_status=201)
    assert_project(project)

    assert project["status"] == "UNDERWRITING"
    assert project["underwriting_stage"] == "PRELIMINARY"
    assert project["preliminary_equity_cents"] == 490198755
    assert project["underwritten_equity_cents"] == 490198755
    assert project["final_equity_cents"] is None
    assert project["dscr"] == pytest.approx(1.2, abs=1e-6)
    assert project["operating_deficit_cents"] == 0
    assert project["committed_credit_dollars_cents"] == 0
    assert project["delivered_credit_dollars_cents"] == 0


def test_subscription_listing_paginates_and_reports_the_filtered_total():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, and it may not be smaller than 1 nor larger than
    100. The `offset` parameter states how many items to skip; it defaults to 0."

    Design: Corner/entities/subscriptions_list_paginates_and_filters_by_fund_status_and_investor
    """
    investor = onboard_investor()
    other = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_2",
    )
    fund = form_fund()
    other_fund = form_fund(
        fund_name="ECP Housing Fund V",
        target_equity_cents=400000000,
        price_per_credit_dollar=0.9050,
        target_yield_pct=0.065,
        subscription_close_date="2027-06-30T00:00:00Z",
    )
    open_subscription(fund, investor, committed_cents=300000000)
    open_subscription(fund, other, committed_cents=100000000)
    open_subscription(other_fund, investor, committed_cents=200000000)

    first_page = api_client.list_subscriptions(
        TEST_USERS["underwriter_headers"], params={"fund_id": fund["id"], "limit": 1}
    )
    rows, meta = assert_paginated_shape(
        first_page, expected_total_count=2, expected_has_more=True, expected_limit=1
    )
    assert len(rows) == 1

    second_page = api_client.list_subscriptions(
        TEST_USERS["underwriter_headers"],
        params={"fund_id": fund["id"], "limit": 1, "offset": 1},
    )
    rows2, meta2 = assert_paginated_shape(
        second_page, expected_total_count=2, expected_has_more=False, expected_offset=1
    )
    assert len(rows2) == 1
    assert rows2[0]["id"] != rows[0]["id"]


def test_subscription_listing_filters_by_investor_and_defaults_its_limit():
    """PRD §4: "GET | `/subscriptions` | List subscriptions, filterable by fund
    and investor".
    PRD §2.3: "Unless a caller requests otherwise, list endpoints return resources
    in ascending order of their creation timestamp."

    Design: Corner/entities/subscriptions_list_paginates_and_filters_by_fund_status_and_investor
    """
    investor = onboard_investor()
    other = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_2",
    )
    fund = form_fund()
    other_fund = form_fund(
        fund_name="ECP Housing Fund V",
        target_equity_cents=400000000,
        price_per_credit_dollar=0.9050,
        target_yield_pct=0.065,
        subscription_close_date="2027-06-30T00:00:00Z",
    )
    open_subscription(fund, investor, committed_cents=300000000)
    open_subscription(fund, other, committed_cents=100000000)
    open_subscription(other_fund, investor, committed_cents=200000000)

    by_investor = api_client.list_subscriptions(
        TEST_USERS["underwriter_headers"], params={"investor_id": other["id"]}
    )
    rows, meta = assert_paginated_shape(by_investor, expected_total_count=1)
    assert len(rows) == 1
    assert rows[0]["investor_id"] == other["id"]

    all_rows = api_client.list_subscriptions(TEST_USERS["underwriter_headers"])
    everything, all_meta = assert_paginated_shape(
        all_rows, expected_total_count=3, expected_limit=10
    )
    assert len(everything) == 3
    assert [s["created_at"] for s in everything] == sorted(
        s["created_at"] for s in everything
    )


def test_fund_get_returns_the_stored_configuration_unchanged():
    """PRD §3.3: "A fund is formed by an `Underwriter` or a `PlatformAdmin`, who
    supplies `fund_name`, `target_equity_cents`, `price_per_credit_dollar`,
    `target_yield_pct`, an optional `close_threshold_pct`, and the two dates
    `subscription_open_date` and `subscription_close_date`."

    Design: Corner/entities/fund_get_returns_the_stored_configuration_unchanged
    """
    investor = onboard_investor()
    fund = form_fund()

    fetched = get_success_data(
        api_client.get_fund(fund["id"], make_investor_headers(investor["id"]))
    )

    assert fetched["fund_name"] == "ECP Housing Fund IV"
    assert fetched["target_equity_cents"] == 500000000
    assert fetched["price_per_credit_dollar"] == pytest.approx(0.9123, abs=1e-9)
    assert fetched["target_yield_pct"] == pytest.approx(0.07, abs=1e-9)
    assert fetched["close_threshold_pct"] == pytest.approx(0.85, abs=1e-9)
    assert_same_instant(fetched["subscription_open_date"], "2026-09-01T00:00:00Z")
    assert_same_instant(fetched["subscription_close_date"], "2026-12-31T00:00:00Z")
