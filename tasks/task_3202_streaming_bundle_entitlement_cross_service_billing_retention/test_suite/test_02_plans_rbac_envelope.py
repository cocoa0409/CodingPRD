"""Plan catalog, RBAC, and envelope coverage."""
from test_helpers import (
    TEST_USERS,
    assert_plan,
    create_plan_payload,
    create_subscriber_account_payload,
    register_account,
    make_subscriber_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]
ANON = TEST_USERS["anonymous_headers"]
DISTRIBUTOR = TEST_USERS["distributor_ops_headers"]


def test_plan_immutability_no_version_field(api, platform_admin_headers):
    """PRD §2.4: "Configuration-style resources — Plan, RetentionOffer,
    WatchlistItem, and RevenueAllocation — carry only id and created_at; both
    updated_at and version are absent from them."

    Design: Corner/entities/plan_immutability_no_version_field
    """
    resp = api.create_plan(
        create_plan_payload(plan_code="DPLUS_ADS", monthly_price_cents=799),
        platform_admin_headers,
    )
    validate_success(resp, 201)
    # An unrelated mutation (account registration) must not touch the plan.
    api.create_subscriber_account(
        create_subscriber_account_payload(email="im1@x.com", full_name="IM One"), ANON
    )
    data = validate_success(api.get_plan("DPLUS_ADS", platform_admin_headers), 200)
    assert_plan(data)
    assert "version" not in data and "updated_at" not in data
    assert data["monthly_price_cents"] == 799


def test_list_plans_pagination_envelope(api, platform_admin_headers):
    """PRD §2.3: "limit defaults to 10, must be at least 1, and may be at most
    100. offset defaults to 0. Every list response carries limit, offset,
    total_count, and has_more inside the meta envelope."

    Design: Corner/entities/list_plans_pagination_envelope
    """
    for code, kind, scope, weights, price in (
        ("P1", "STANDALONE", ["DPLUS"], None, 799),
        ("P2", "STANDALONE", ["HULU"], None, 899),
        ("P3", "BUNDLE", ["DPLUS", "HULU"], {"DPLUS": 0.5, "HULU": 0.5}, 1999),
    ):
        resp = api.create_plan(
            create_plan_payload(
                plan_code=code,
                plan_kind=kind,
                service_scope=scope,
                component_weights=weights,
                monthly_price_cents=price,
            ),
            platform_admin_headers,
        )
        validate_success(resp, 201)
    resp = api.list_plans(platform_admin_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(data) == 3


def test_bundle_plan_bad_weights_rejected(api, platform_admin_headers):
    """PRD §3.1: "A BUNDLE plan must list both DPLUS and HULU in its
    service_scope and must carry component_weights — a per-service revenue
    split such as 0.45 for DPLUS and 0.55 for HULU — whose weights each sit
    strictly between 0 and 1 and sum to exactly 1.0 (tolerating a deviation no
    larger than one billionth)."
    PRD §3.1: "Violations of these shape rules are rejected with
    ERR_INVALID_PLAN_SHAPE (HTTP 422)."

    Design: Corner/validations/bundle_plan_bad_weights_rejected
    """
    bad = api.create_plan(
        create_plan_payload(
            plan_code="BAD_BUNDLE",
            plan_kind="BUNDLE",
            service_scope=["DPLUS", "HULU"],
            monthly_price_cents=1099,
            component_weights={"DPLUS": 0.45, "HULU": 0.45},
        ),
        platform_admin_headers,
    )
    validate_error(bad, "ERR_INVALID_PLAN_SHAPE", 422)
    good = api.create_plan(
        create_plan_payload(
            plan_code="GOOD_BUNDLE",
            plan_kind="BUNDLE",
            service_scope=["DPLUS", "HULU"],
            monthly_price_cents=1099,
            component_weights={"DPLUS": 0.45, "HULU": 0.55},
        ),
        platform_admin_headers,
    )
    validate_success(good, 201)


def test_invalid_pricing_plan_price_floor(api, platform_admin_headers):
    """PRD §3.1: "Independently, monthly_price_cents must be at least 100 cents
    — a cheaper plan is rejected with ERR_INVALID_PRICING (HTTP 422)."

    Design: Corner/validations/invalid_pricing_plan_price_floor
    """
    too_cheap = api.create_plan(
        create_plan_payload(plan_code="TOO_CHEAP", monthly_price_cents=99),
        platform_admin_headers,
    )
    validate_error(too_cheap, "ERR_INVALID_PRICING", 422)
    at_floor = api.create_plan(
        create_plan_payload(plan_code="AT_FLOOR", monthly_price_cents=100),
        platform_admin_headers,
    )
    validate_success(at_floor, 201)


def test_anonymous_cannot_create_plans(api, anonymous_headers):
    """PRD §2.1: "If the role is recognized but not permitted for the endpoint,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "the Anonymous role exists solely to register a new subscriber
    account."

    Design: Corner/rbac/anonymous_cannot_create_plans
    """
    resp = api.create_plan(create_plan_payload(plan_code="X"), anonymous_headers)
    validate_error(resp, "ERR_UNAUTHORIZED", 403)


def test_subscriber_cannot_suspend_account(api):
    """PRD §3.2: "Suspension is a blunt instrument available to Support and
    PlatformAdmin."
    PRD §2.1: "If the role is recognized but not permitted for the endpoint,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_suspend_account
    """
    account = register_account(email="rb2@x.com")
    hdrs = make_subscriber_headers(account["id"])
    resp = api.suspend_account(account["id"], hdrs)
    validate_error(resp, "ERR_UNAUTHORIZED", 403)


def test_subscriber_cannot_drive_clock_or_renewal(api):
    """PRD §2.5: "A PlatformAdmin advances the clock by supplying a target
    instant to_iso8601."
    PRD §3.11: "Renewal is driven by a test-driving capability available to
    PlatformAdmin: for a named billing_account_id whose period is due —
    period_end at or before the logical clock, closed at the boundary — it
    runs the collection with a forced outcome."
    PRD §2.1: "If the role is recognized but not permitted for the endpoint,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_drive_clock_or_renewal
    """
    from test_helpers import setup_account_with_billing

    account, billing, hdrs = setup_account_with_billing(email="rb3@x.com")
    resp = api.run_renewal(
        {"billing_account_id": billing["id"], "outcome": "SUCCEEDED"}, hdrs
    )
    validate_error(resp, "ERR_UNAUTHORIZED", 403)


def test_subscriber_cannot_touch_other_account(api):
    """PRD §2.1: "A subscriber acting on a resource owned by a different
    account is rejected with ERR_FORBIDDEN_NOT_OWNER (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_touch_other_account
    """
    account_a = register_account(email="rb4a@x.com")
    account_b = register_account(email="rb4b@x.com")
    hdrs_a = make_subscriber_headers(account_a["id"])
    resp = api.get_subscriber_account(account_b["id"], hdrs_a)
    validate_error(resp, "ERR_FORBIDDEN_NOT_OWNER", 403)


def test_distributor_ops_cannot_create_offers_or_read_revenue_scope(
    api, distributor_ops_headers
):
    """PRD §2.1: "`DistributorOps` manages distributor-billed subscriptions and likewise
    cannot create plans or offers or drive the clock; `PlatformAdmin` is the
    full operator whose permission set is a superset of every other role."
    PRD §4: the revenue-report endpoint is authorized for "Support,
    PlatformAdmin, DistributorOps".
    PRD §3.12: "The report returns the total_cents collected in the window, a
    per_service breakdown, and the invoice_count of contributing invoices."

    Design: Corner/rbac/distributor_ops_cannot_create_offers_or_read_revenue_scope
    """
    denied = api.create_retention_offer(
        {
            "offer_code": "NOPE",
            "discount_cents": 100,
            "duration_months": 1,
            "max_redemptions_per_account": 1,
            "eligible_biller_types": ["DISTRIBUTOR"],
            "eligible_plan_kinds": ["STANDALONE"],
        },
        distributor_ops_headers,
    )
    validate_error(denied, "ERR_UNAUTHORIZED", 403)
    report = api.get_revenue_report(
        distributor_ops_headers,
        params={
            "from_iso8601": "2026-09-01T00:00:00Z",
            "to_iso8601": "2026-10-01T00:00:00Z",
        },
    )
    data = validate_success(report, 200)
    assert data["total_cents"] == 0
    assert data["invoice_count"] == 0


def test_support_has_full_account_mutation_but_no_config(api, support_headers):
    """PRD §3.2: "Suspension is a blunt instrument available to Support and
    PlatformAdmin."
    PRD §3.2: "Reactivation requires the account to be SUSPENDED and,
    critically, that no subscription of the account remains in PAST_DUE — the
    money must be fixed before the account can come back."
    PRD §2.1: "`Support` is a customer-service operator who may act on any account but
    may not create plans or offers nor drive the clock or renewals;
    `DistributorOps` manages distributor-billed subscriptions and likewise
    cannot create plans or offers or drive the clock; `PlatformAdmin` is the
    full operator whose permission set is a superset of every other role."

    Design: Corner/rbac/support_has_full_account_mutation_but_no_config
    """
    account = register_account(email="rb6@x.com")
    suspended = api.suspend_account(account["id"], support_headers)
    validate_success(suspended, 200)
    reactivated = api.reactivate_account(account["id"], support_headers)
    data = validate_success(reactivated, 200)
    assert data["account_status"] == "ACTIVE"
    denied = api.create_plan(create_plan_payload(plan_code="X2"), support_headers)
    validate_error(denied, "ERR_UNAUTHORIZED", 403)
