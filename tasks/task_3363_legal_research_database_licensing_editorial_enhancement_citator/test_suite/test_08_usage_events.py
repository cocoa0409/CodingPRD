"""Metered usage: ledger-entry shape, seat and subscription gates, bulk-rate
boundary, scope enforcement branches, and the conditional matter-code rule
(PRD §2.5, §3.5)."""
from test_helpers import (
    CLOCK_SEP_10,
    ApiErrorId,
    assert_usage_event,
    assign_seat,
    create_account,
    create_plan,
    create_subscription,
    make_researcher_headers,
    release_seat,
    set_clock,
    setup_subscribed_user,
    usage_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

_LICENSING = TEST_USERS["licensing_manager_headers"]
_BILLING = TEST_USERS["billing_admin_headers"]


def test_usage_event_immutable_shape(api):
    """PRD §2.5: "Two resources are deliberate exceptions, behaving as immutable
    ledger entries rather than mutable records: a UsageEvent and a RoyaltyStatement
    each carry only `id` and `created_at`."
    PRD §3.5: "The caller never names the subscription: the system derives the
    event's `subscription_id` from the acting user's `ACTIVE` seat and copies
    `X-User-ID` into the event's `user_id`. The event's `occurred_at` is stamped
    from the logical clock at creation and is immutable thereafter."

    Design: Corner/entities/usage_event_immutable_shape
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Imm Plan", "practice_area": "ALL",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="i@imm.com",
    )
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="TAX"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    data = validate_success(resp, 201)
    assert_usage_event(data)
    assert data["occurred_at"].startswith("2026-09-10T00:00:00"), (
        f"occurred_at must be stamped from the logical clock, got {data['occurred_at']}"
    )
    assert data["in_scope"] is True, "plan practice_area ALL matches any tag"
    assert data["subscription_id"] == ctx["subscription"]["id"]
    assert data["user_id"] == ctx["user"]["id"]


def test_usage_event_on_suspended_subscription_rejected(api):
    """PRD §3.5: "The subscription behind the seat must be `ACTIVE`, else
    `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409)."
    PRD §3.4: "Suspension does not release seats; it only bars new usage, as §3.5
    describes."

    Design: Difficulty/cross_entity_state_dependency/usage_event_gated_by_subscription_status
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Gate Plan"}, user_email="g@gate.com")
    sub_id = ctx["subscription"]["id"]
    validate_success(
        api.transition_subscription(sub_id, {"target_status": "SUSPENDED"}, _LICENSING), 200
    )
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)


def test_usage_event_on_suspended_subscription_records_nothing(api):
    """PRD §3.5: "The subscription behind the seat must be `ACTIVE`, else
    `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/usage_event_gated_by_subscription_status
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Gate Plan"}, user_email="g@gate.com")
    sub_id = ctx["subscription"]["id"]
    validate_success(
        api.transition_subscription(sub_id, {"target_status": "SUSPENDED"}, _LICENSING), 200
    )
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)
    _, meta = validate_paginated(
        api.list_usage_events(_BILLING, params={"user_id": ctx["user"]["id"]})
    )
    assert meta["total_count"] == 0, "a rejected event must not be recorded"


def test_usage_event_without_seat_rejected(api):
    """PRD §3.5: "The acting user must actually hold an `ACTIVE` seat, else
    `ERR_NO_SEAT_HELD` (HTTP 409)."
    PRD §3.5: "The caller never names the subscription: the system derives the
    event's `subscription_id` from the acting user's `ACTIVE` seat and copies
    `X-User-ID` into the event's `user_id`."

    Design: Corner/validations/usage_event_without_seat_rejected
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "NoSeat Plan"}, seats_total=2,
                                user_email="n@noseat.com")
    release_seat(ctx["subscription"]["id"], ctx["account"]["id"], ctx["user"]["id"])
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEAT_HELD, 409)


def test_bulk_hourly_limit_boundary(api):
    """PRD §3.5: "When the trailing-hour count has already reached the plan's
    `bulk_hourly_limit`, or the calendar-day count has already reached its
    `bulk_daily_limit`, the new event is rejected with `ERR_BULK_RATE_EXCEEDED`
    (HTTP 422); an event that merely brings either count up to the limit is still
    admitted, and only the one after it is refused."

    Design: Corner/validations/bulk_hourly_limit_boundary
    """
    set_clock("2026-09-10T12:00:00Z")
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Bulk Plan", "practice_area": "ALL",
                        "included_searches": 100, "included_doc_views": 100,
                        "bulk_hourly_limit": 3},
        user_email="b@bulk.com",
    )
    headers = make_researcher_headers(ctx["user"]["id"])
    for i in range(3):
        resp = api.create_usage_event(
            usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"), headers,
        )
        validate_success(resp, 201)
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"), headers,
    )
    validate_error(resp, ApiErrorId.ERR_BULK_RATE_EXCEEDED, 422)


def test_scope_hard_rejects_out_of_scope_event(api):
    """PRD §3.5: "Scope enforcement then compares the event's `practice_area_tag` to
    the plan's `practice_area`: a match, or a plan scoped to `ALL`, records the
    event with `in_scope` true; a mismatch on a `SOFT` plan is recorded with
    `in_scope` false, while a mismatch on a `HARD` plan is rejected with
    `ERR_USAGE_OUT_OF_SCOPE` (HTTP 422)."

    Design: Corner/validations/scope_hard_rejects_out_of_scope_event
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Hard Plan", "scope_enforcement": "HARD",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="h@hard.com",
    )
    resp = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="TAX"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_USAGE_OUT_OF_SCOPE, 422)
    _, meta = validate_paginated(
        api.list_usage_events(_BILLING, params={"user_id": ctx["user"]["id"]})
    )
    assert meta["total_count"] == 0, "a rejected out-of-scope event must not be recorded"


def test_scope_soft_records_out_of_scope_flagged(api):
    """PRD §3.5: "Scope enforcement then compares the event's `practice_area_tag` to
    the plan's `practice_area`: a match, or a plan scoped to `ALL`, records the
    event with `in_scope` true; a mismatch on a `SOFT` plan is recorded with
    `in_scope` false, while a mismatch on a `HARD` plan is rejected with
    `ERR_USAGE_OUT_OF_SCOPE` (HTTP 422). The `in_scope` flag is computed, never
    supplied."

    Design: Corner/validations/scope_soft_records_out_of_scope_flagged
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(
        plan_overrides={"name": "Soft Plan", "scope_enforcement": "SOFT",
                        "included_searches": 10, "included_doc_views": 10},
        user_email="s@soft.com",
    )
    headers = make_researcher_headers(ctx["user"]["id"])
    out_of_scope = validate_success(api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="TAX"), headers,
    ), 201)
    assert out_of_scope["in_scope"] is False

    in_scope = validate_success(api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"), headers,
    ), 201)
    assert in_scope["in_scope"] is True


def test_matter_code_required_on_recovery_account(api):
    """PRD §3.5: "The final gate is referential: when the subscription's account has
    `cost_recovery_enabled` set, every event must carry a `matter_code`, and when
    it does not, the `matter_code` must be omitted entirely — either violation
    fails with `ERR_MATTER_CODE_REQUIRED` (HTTP 422)."

    Design: Corner/validations/matter_code_required_on_recovery_account
    """
    set_clock(CLOCK_SEP_10)
    plan = create_plan(
        name="MC Plan", practice_area="ALL", cost_recovery_allowed=True,
        included_searches=10, included_doc_views=10,
    )
    recovery = create_account(org_name="Rec Co", cost_recovery_enabled=True)
    plain = create_account(org_name="NoRec Co", cost_recovery_enabled=False)
    sub_r = create_subscription(recovery["id"], plan["id"])
    sub_n = create_subscription(plain["id"], plan["id"])
    user_r = assign_seat(sub_r["id"], recovery["id"], email="r@mc.com", full_name="R")
    user_n = assign_seat(sub_n["id"], plain["id"], email="n@mc.com", full_name="N")

    missing = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"),
        make_researcher_headers(user_r["id"]),
    )
    validate_error(missing, ApiErrorId.ERR_MATTER_CODE_REQUIRED, 422)

    supplied = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION", matter_code="M-X"),
        make_researcher_headers(user_n["id"]),
    )
    validate_error(supplied, ApiErrorId.ERR_MATTER_CODE_REQUIRED, 422)

    ok = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION", matter_code="M-X"),
        make_researcher_headers(user_r["id"]),
    )
    data = validate_success(ok, 201)
    assert data["matter_code"] == "M-X"
