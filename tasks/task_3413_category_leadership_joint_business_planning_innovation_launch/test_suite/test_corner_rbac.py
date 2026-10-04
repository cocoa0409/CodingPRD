"""Corner queue — role-based access control denials and retailer scoping.

Each test translates one corner-design `rbac` instance and cites the PRD
sentence that pins the asserted rule. RetailerBuyer probes on owned resources
use the entity-backed identity (``make_retailer_buyer_headers(retailer_id)``).
"""
from test_helpers import (
    ApiErrorId,
    create_category,
    create_forecast_commit_payload,
    create_plan,
    create_plan_payload,
    create_published_forecast,
    create_retailer,
    get_fund,
    get_plan,
    make_retailer_buyer_headers,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_paginated,
)


def test_retailer_buyer_cannot_create_plan(api):
    """PRD §2.1: "A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/jbp/plans` | Create a JointBusinessPlan (lands `PROPOSED`, round 1) | ManufacturerPlanner |"

    Plan creation is exclusive to ManufacturerPlanner; a RetailerBuyer attempt
    against existing reference data fails `ERR_FORBIDDEN`.

    Design: Corner/rbac/retailer_buyer_cannot_create_plan
    """
    retailer = create_retailer()
    category = create_category()
    validate_error(
        api.create_plan(
            create_plan_payload(retailer["id"], category["id"]),
            make_retailer_buyer_headers(retailer["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_manufacturer_cannot_commit_forecast(api, manufacturer_planner_headers):
    """PRD §3.7: "Commitment is the retailer's move. The `RetailerBuyer` of the plan's retailer commits volume against a forecast by supplying `committed_cases`, which must be strictly positive."
    PRD §4: "| POST | `/jbp/forecasts/{id}/commit` | Commit retailer volume against a published, uncommitted forecast | RetailerBuyer |"
    PRD §2.1: "A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    A ManufacturerPlanner commit against a valid PUBLISHED forecast fails
    `ERR_FORBIDDEN`; the forecast stays UNCOMMITTED.

    Design: Corner/rbac/manufacturer_cannot_commit_forecast
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    forecast = create_published_forecast(plan_id)

    validate_error(
        api.commit_forecast(
            forecast["id"], create_forecast_commit_payload(1100), manufacturer_planner_headers
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )

    forecasts, _ = validate_paginated(api.list_forecasts(plan_id, manufacturer_planner_headers))
    reloaded = [f for f in forecasts if f["id"] == forecast["id"]]
    assert len(reloaded) == 1
    assert reloaded[0]["commit_status"] == "UNCOMMITTED", (
        f"a forbidden commit must not move the axis, got {reloaded[0]['commit_status']}"
    )


def test_category_advisor_cannot_post_accrual(api, category_advisor_headers):
    """PRD §3.6: "A `FinanceAnalyst` posts one accrual per period against a fund, supplying the `period` as a `YYYY-MM` string and the period's `invoiced_sales_cents`"
    PRD §4: "| POST | `/jbp/funds/{id}/accruals` | Post one period's invoiced sales into the fund | FinanceAnalyst |"
    PRD §2.1: "A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    A CategoryAdvisor accrual posting fails `ERR_FORBIDDEN` and no invoiced
    sales accumulate.

    Design: Corner/rbac/advisor_cannot_post_accrual
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]

    validate_error(
        api.post_fund_accrual(
            fund_id, {"period": "2027-01", "invoiced_sales_cents": 100000}, category_advisor_headers
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )

    assert get_fund(fund_id)["total_invoiced_cents"] == 0, (
        "a forbidden posting must not accumulate total_invoiced_cents"
    )


def test_retailer_scope_mismatch_on_negotiation_counter(api):
    """PRD §2.1: "When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting `Retailer`: ownership checks on any resource compare the `retailer_id` of the `JointBusinessPlan` that owns the target resource — reached either directly through a plan path parameter or through the target entity's plan, launch, or fund chain — against `X-User-ID`."
    PRD §2.1: "A mismatch is rejected with `ERR_RETAILER_SCOPE_MISMATCH` (HTTP 403)."

    Retailer B's buyer countering retailer A's plan fails
    `ERR_RETAILER_SCOPE_MISMATCH` — distinct from `ERR_FORBIDDEN`, because the
    role itself is lawful for negotiate.

    Design: Corner/rbac/retailer_scope_mismatch_on_counter
    """
    retailer_a = create_retailer()
    retailer_b = create_retailer(name="Retailer Beta", channels=["GROCERY"])
    category = create_category()
    plan = create_plan(retailer_a["id"], category["id"])

    validate_error(
        api.negotiate_plan(
            plan["id"], {"growth_target_pct": 9}, make_retailer_buyer_headers(retailer_b["id"])
        ),
        ApiErrorId.ERR_RETAILER_SCOPE_MISMATCH,
    )

    reloaded = get_plan(plan["id"])
    assert reloaded["status"] == "PROPOSED"
    assert reloaded["negotiation_round"] == 1, (
        f"a scope-refused counter must not climb the round, got {reloaded['negotiation_round']}"
    )


def test_platform_admin_cannot_negotiate(api, platform_admin_headers):
    """PRD §4: "| POST | `/jbp/plans/{id}/negotiate` | Counter (retailer, from `PROPOSED`) or re-propose (manufacturer, from `COUNTERED`) | ManufacturerPlanner, RetailerBuyer |"
    PRD §2.1: "A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    PlatformAdmin stands outside the negotiation role pair; its negotiate call
    fails `ERR_FORBIDDEN`.

    Design: Corner/rbac/platform_admin_cannot_negotiate
    """
    scenario = setup_proposed_plan()
    validate_error(
        api.negotiate_plan(scenario["plan"]["id"], {"growth_target_pct": 9}, platform_admin_headers),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_clock_set_is_platform_admin_exclusive(api, manufacturer_planner_headers):
    """PRD §2.4: "An admin-only, test-driving capability sets the clock: a `PlatformAdmin` supplies a `to_iso8601` instant, and a successful call answers 200 OK with the resulting `current_utc`."
    PRD §2.1: "It seeds reference data — creating retailers and categories — and is the only role allowed to drive the server's logical clock."
    PRD §2.1: "A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    A ManufacturerPlanner clock set fails `ERR_FORBIDDEN`.

    Design: Corner/rbac/clock_set_requires_platform_admin
    """
    validate_error(
        api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, manufacturer_planner_headers),
        ApiErrorId.ERR_FORBIDDEN,
    )


def test_retailer_buyer_reading_other_retailers_plan_refused(api):
    """PRD §2.1: "A mismatch is rejected with `ERR_RETAILER_SCOPE_MISMATCH` (HTTP 403). The same scope restriction applies to reads: a `RetailerBuyer` browsing list or detail endpoints sees only its own retailer's data."
    PRD §2.9: "Retailer scope: for any request made as `RetailerBuyer`, `X-User-ID` equals the `retailer_id` of the plan that owns the target resource, else `ERR_RETAILER_SCOPE_MISMATCH`."

    The scope restriction covers reads: retailer B's buyer GETting retailer A's
    plan detail is refused, not served.

    Design: Corner/rbac/retailer_buyer_read_other_retailer_plan_returns_scope_mismatch
    """
    retailer_a = create_retailer()
    retailer_b = create_retailer(name="Retailer Beta", channels=["GROCERY"])
    category = create_category()
    plan = create_plan(retailer_a["id"], category["id"])

    validate_error(
        api.get_plan(plan["id"], make_retailer_buyer_headers(retailer_b["id"])),
        ApiErrorId.ERR_RETAILER_SCOPE_MISMATCH,
    )
