"""Authority verification coverage, lazy expiry, RBAC, and posting refunds."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    set_test_clock, create_broker, create_carrier,
    setup_verified_broker, setup_verified_carrier, post_load,
    create_load_post_payload, create_authority_verification_payload,
    get_subscription,
    make_broker_admin_headers, make_carrier_admin_headers,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["compliance_analyst_headers"]


def test_insurance_windows_gap_breaks_coverage_contiguity():
    """PRD §3.1: "Verification is a judgment call by a `ComplianceAnalyst`: it
    requires a non-empty `authority_reference` and insurance coverage
    satisfied against the current clock; if the windows contain a gap or do
    not cover the present moment, the verify attempt is rejected with
    `ERR_INSURANCE_WINDOW_GAP` (HTTP 422)." and "`covered_until` becomes the
    maximum `effective_to` over the merged contiguous prefix — null when there
    are no windows at all. `coverage_gap_detected` is true when some window's
    `effective_from` falls strictly after the running `covered_until` at its
    turn."

    Design: Difficulty/resource_temporal_overlap/insurance_windows_gap_breaks_coverage_contiguity
    """
    set_test_clock()
    broker = create_broker()
    bid = broker["id"]
    bh = make_broker_admin_headers(bid)

    gap = get_success_data(api_client.create_authority_verification(
        create_authority_verification_payload(
            "broker", bid, authority_reference="MC-900-AUTH",
            insurance_windows=[
                {"effective_from": "2026-01-01T00:00:00Z", "effective_to": "2026-06-01T00:00:00Z"},
                {"effective_from": "2026-06-02T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"},
            ]), bh))
    ok = get_success_data(api_client.create_authority_verification(
        create_authority_verification_payload(
            "broker", bid, authority_reference="MC-900-AUTH-2",
            insurance_windows=[
                {"effective_from": "2026-01-01T00:00:00Z", "effective_to": "2026-06-01T00:00:00Z"},
                {"effective_from": "2026-06-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"},
            ]), bh))

    resp = api_client.verify_authority(gap["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_WINDOW_GAP)
    g = get_success_data(api_client.get_authority_verification(gap["id"], ADMIN))
    assert g["status"] == "PENDING"
    assert g["coverage_gap_detected"] is True

    v = validate_success(api_client.verify_authority(ok["id"], ANALYST))
    assert v["status"] == "VERIFIED"
    assert v["insurance_ok"] is True
    assert v["covered_until"].startswith("2027-01-01T00:00:00")


def test_authority_verification_expires_lazily_on_read_after_clock_passes_covered_until():
    """PRD §3.1: "A `VERIFIED` record transitions automatically to `EXPIRED`
    once the logical clock reaches `covered_until` — applied eagerly on clock
    set and lazily on read — and may be returned to `VERIFIED` after the org
    updates its `insurance_windows` to restore coverage and the analyst
    verifies again." and §3.1: "`insurance_ok` holds only when no gap was
    detected, `covered_until` is not null, and the first window's
    `effective_from` is at or before the current logical clock while the clock
    is strictly before `covered_until`."

    Design: Corner/cross_cutting_complexity_layers/authority_verification_expires_lazily_on_read_after_clock_passes_covered_until
    """
    set_test_clock()
    broker = create_broker()
    bid = broker["id"]
    bh = make_broker_admin_headers(bid)
    av = get_success_data(api_client.create_authority_verification(
        create_authority_verification_payload("broker", bid), bh))
    v = validate_success(api_client.verify_authority(av["id"], ANALYST))
    assert v["status"] == "VERIFIED"

    set_test_clock("2026-12-31T23:59:59Z")
    d1 = get_success_data(api_client.get_authority_verification(av["id"], ADMIN))
    assert d1["status"] == "VERIFIED"
    assert d1["insurance_ok"] is True
    assert d1["version"] == v["version"]

    set_test_clock("2027-01-01T00:00:00Z")
    d2 = get_success_data(api_client.get_authority_verification(av["id"], ADMIN))
    assert d2["status"] == "EXPIRED"
    assert d2["insurance_ok"] is False
    assert d2["version"] == v["version"]


def test_carrier_admin_cannot_create_load_post():
    """PRD §2.1: "Only a `BrokerAdmin` may post loads, withdraw loads, file
    credit disputes, and submit rebuttals." and "a role that is not permitted
    for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/roles/carrier_admin_cannot_create_load_post
    """
    set_test_clock()
    carrier = create_carrier()
    resp = api_client.create_load_post(
        create_load_post_payload(), make_carrier_admin_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_broker_admin_cannot_withdraw_another_brokers_load():
    """PRD §2.1: "Ownership-scoped operations add a further check: when the
    acting entity-backed org does not own the target resource, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/roles/broker_admin_cannot_withdraw_another_brokers_load
    """
    set_test_clock()
    bctx = setup_verified_broker()
    load = post_load(bctx)
    other = create_broker()
    resp = api_client.withdraw_load_post(load["id"],
                                         make_broker_admin_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    from test_helpers import get_load
    assert get_load(load["id"])["status"] == "OPEN"


def test_missing_auth_headers_returns_400():
    """PRD §2.1: "A request missing either header, or presenting a malformed
    value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
    400)."

    Design: Corner/errors/missing_auth_headers_returns_400
    """
    resp = api_client.list_broker_orgs(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_post_then_timely_withdraw_restores_posting_quota():
    """PRD §3.3: "An early exit is partially rewarded: when the logical clock
    at withdrawal is no more than 24 hours after the post's `created_at`, the
    owning subscription's `posts_used` is decremented by 1, refunding the
    post." and §3.2: "`posts_used`, the number of posts created in the current
    period net of within-24-hour withdrawal refunds"

    Design: Difficulty/compensating_invariant/post_then_timely_withdraw_restores_posting_quota
    """
    set_test_clock()
    bctx = setup_verified_broker(plan_overrides={
        "code": "PRO", "monthly_posting_allowance": 3, "overage_tier1_limit": 2,
        "overage_hard_cap": 10, "search_daily_limit": 50,
        "analytics_depth": "LANE_LEVEL", "requires_data_contribution": False})
    sub_id = bctx["subscription"]["id"]

    sub0 = get_subscription(sub_id)
    assert sub0["posts_used"] == 0
    assert sub0["period_price_cents"] == 26900

    l1 = post_load(bctx, rate_offer_cents=150000)
    r = validate_success(api_client.withdraw_load_post(l1["id"], bctx["broker_headers"]))
    assert r["status"] == "WITHDRAWN"
    sub1 = get_subscription(sub_id)
    assert sub1["posts_used"] == 0
    assert sub1["period_price_cents"] == 26900

    l2 = post_load(bctx, rate_offer_cents=150000)
    set_test_clock("2026-08-02T00:00:01Z")
    r2 = validate_success(api_client.withdraw_load_post(l2["id"], bctx["broker_headers"]))
    assert r2["status"] == "WITHDRAWN"
    sub2 = get_subscription(sub_id)
    assert sub2["posts_used"] == 1
    assert sub2["period_price_cents"] == 26900
