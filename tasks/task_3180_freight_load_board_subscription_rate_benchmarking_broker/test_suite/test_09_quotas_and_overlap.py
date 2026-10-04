"""Posting quota, search limit, validation ordering, and overlap rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, setup_verified_broker, setup_verified_carrier,
    post_load, post_truck, create_load_post_payload, create_truck_post_payload,
    get_subscription,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_posting_quota_rejects_at_exactly_hard_cap():
    """PRD §3.3: "The fiscal gate is a hard cap: a post may be created only
    while the subscription's `posts_used` is strictly less than the plan's
    `monthly_posting_allowance` plus its `overage_hard_cap`; when `posts_used`
    equals that sum, the create is rejected with `ERR_POSTING_QUOTA_EXCEEDED`
    (HTTP 402)."

    Design: Difficulty/boundary_precision_check/posting_quota_rejects_at_exactly_hard_cap
    """
    set_test_clock()
    bctx = setup_verified_broker(plan_overrides={
        "code": "BASIC", "monthly_posting_allowance": 2, "overage_tier1_limit": 1,
        "overage_hard_cap": 1, "search_daily_limit": 10, "analytics_depth": "NONE",
        "requires_data_contribution": False})
    post_load(bctx)
    post_load(bctx)
    third = validate_success(api_client.create_load_post(
        create_load_post_payload(), bctx["broker_headers"]), expected_status=201)
    sub = get_subscription(bctx["subscription"]["id"])
    assert sub["posts_used"] == 3

    resp = api_client.create_load_post(create_load_post_payload(), bctx["broker_headers"])
    validate_error(resp, ApiErrorId.ERR_POSTING_QUOTA_EXCEEDED)
    assert get_subscription(bctx["subscription"]["id"])["posts_used"] == 3


def test_subscription_inactive_state_beats_posting_quota_fiscal():
    """PRD §2.7: "Fourth, state admissibility: the org must be `ACTIVE`, the
    subscription must be `ACTIVE`" ... "Ninth and last, fiscal limits: the
    posting hard cap and the daily search limit" and §3.2: "Any operation that
    requires an active subscription — posting, booking, benchmark access —
    rejects a `PAST_DUE`, `SUSPENDED`, or `CANCELLED` subscription with
    `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/subscription_inactive_state_beats_posting_quota_fiscal
    """
    set_test_clock()
    bctx = setup_verified_broker(plan_overrides={
        "code": "BASIC", "monthly_posting_allowance": 2, "overage_tier1_limit": 1,
        "overage_hard_cap": 1, "search_daily_limit": 10, "analytics_depth": "NONE",
        "requires_data_contribution": False})
    for _ in range(3):
        post_load(bctx)
    get_success_data(api_client.mark_past_due(bctx["subscription"]["id"], ADMIN))

    resp = api_client.create_load_post(create_load_post_payload(), bctx["broker_headers"])
    err = validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)
    assert resp.json()["data"]["error_id"] != "ERR_POSTING_QUOTA_EXCEEDED"


def test_truck_window_overlap_temporal_beats_posting_quota_fiscal():
    """PRD §2.7: "Seventh, temporal rules: truck availability window overlap,
    pickup window ordering, and the 90-day dispute filing window" ... "Ninth
    and last, fiscal limits: the posting hard cap and the daily search limit"
    and §3.3: "a new truck is rejected with `ERR_TRUCK_WINDOW_OVERLAP` (HTTP
    409) when any existing `AVAILABLE` truck of the same carrier has
    `available_from` strictly before the new `available_until` and
    `available_until` strictly after the new `available_from`."

    Design: Difficulty/priority_pair_validation_conflict/truck_window_overlap_temporal_beats_posting_quota_fiscal
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "BASIC", "monthly_posting_allowance": 1, "overage_tier1_limit": 0,
        "overage_hard_cap": 0, "search_daily_limit": 10, "analytics_depth": "NONE",
        "requires_data_contribution": False})
    post_truck(cctx)  # posts_used == 1 == hard cap

    resp = api_client.create_truck_post(
        create_truck_post_payload(available_from="2026-08-03T00:00:00Z",
                                  available_until="2026-08-06T00:00:00Z"),
        cctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_OVERLAP)
    assert resp.json()["data"]["error_id"] != "ERR_POSTING_QUOTA_EXCEEDED"


def test_truck_post_half_open_window_overlap_rejected_adjacency_allowed():
    """PRD §3.3: "Adjacency is not overlap — a new truck whose
    `available_from` equals an existing truck's `available_until`, or whose
    `available_until` equals an existing `available_from`, is allowed."

    Design: Difficulty/resource_temporal_overlap/truck_post_half_open_window_overlap_rejected_adjacency_allowed
    """
    set_test_clock()
    cctx = setup_verified_carrier(plan_overrides={
        "code": "ENTERPRISE", "monthly_posting_allowance": 100,
        "overage_tier1_limit": 50, "overage_hard_cap": 50,
        "search_daily_limit": 100, "analytics_depth": "FULL",
        "requires_data_contribution": False})
    post_truck(cctx)  # [2026-08-02, 2026-08-05)

    adj = validate_success(api_client.create_truck_post(
        create_truck_post_payload(available_from="2026-08-05T00:00:00Z",
                                  available_until="2026-08-08T00:00:00Z"),
        cctx["carrier_headers"]), expected_status=201)
    assert adj["status"] == "AVAILABLE"

    resp = api_client.create_truck_post(
        create_truck_post_payload(available_from="2026-08-04T23:59:59Z",
                                  available_until="2026-08-09T00:00:00Z"),
        cctx["carrier_headers"])
    validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_OVERLAP)

    rows, meta = validate_paginated(api_client.list_truck_posts(
        cctx["carrier_headers"],
        params={"carrier_org_id": cctx["carrier"]["id"], "status": "AVAILABLE"}))
    assert len(rows) == 2


def test_search_limit_exceeded_at_plan_daily_cap():
    """PRD §3.3: "Every search performed by a `CarrierAdmin` caller increments
    `searches_used_today` on that carrier's subscription, and once the counter
    equals the plan's `search_daily_limit`, further searches that day are
    rejected with `ERR_SEARCH_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/search_limit_exceeded_at_plan_daily_cap
    """
    set_test_clock()
    bctx = setup_verified_broker()
    post_load(bctx)
    cctx = setup_verified_carrier(plan_overrides={
        "code": "BASIC", "monthly_posting_allowance": 5, "overage_tier1_limit": 2,
        "overage_hard_cap": 2, "search_daily_limit": 2, "analytics_depth": "NONE",
        "requires_data_contribution": False})

    p = {"origin": "DAL"}
    validate_success(api_client.list_load_posts(cctx["carrier_headers"], params=p))
    validate_success(api_client.list_load_posts(cctx["carrier_headers"], params=p))
    resp = api_client.list_load_posts(cctx["carrier_headers"], params=p)
    validate_error(resp, ApiErrorId.ERR_SEARCH_LIMIT_EXCEEDED)

    set_test_clock("2026-08-02T00:00:00Z")
    validate_success(api_client.list_load_posts(cctx["carrier_headers"], params=p))
