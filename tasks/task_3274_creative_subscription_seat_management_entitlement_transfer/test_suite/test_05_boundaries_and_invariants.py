"""Boundary precision and compensating-invariant tests (depth queue A)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_subscription,
    activate_subscription,
    create_active_subscription,
    create_end_user,
    create_asset,
    create_cancellation_request,
    mint_seat_for_active_subscription,
    assign_seat,
    get_seat,
    get_subscription,
    get_end_user,
    get_asset,
    set_clock,
    validate_success,
    validate_error,
    make_org_admin_headers,
    make_end_user_headers,
)


def _monthly_cancellation_setup(api, org_name="O10"):
    """Org with MONTHLY plan (window 14, etf 0) and TWO activated one-seat
    subscriptions, each with its own PENDING cancellation request."""
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=org_name, org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email=f"oa@{org_name}.com", full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code=f"{org_name}-P", segment="TEAM",
                       billing_model="MONTHLY", monthly_price_cents=3000,
                       annual_monthly_price_cents=3000, storage_gb_per_seat=20,
                       cancellation_window_days=14, etf_rate_pct=0)
    create_product_version(plan["id"])
    sub_a = activate_subscription(
        create_subscription(org["id"], plan["id"], seats_purchased=1)["id"])
    sub_b = activate_subscription(
        create_subscription(org["id"], plan["id"], seats_purchased=1)["id"])
    cr_a = create_cancellation_request(sub_a["id"], admin["id"], headers)
    cr_b = create_cancellation_request(sub_b["id"], admin["id"], headers)
    return {"org": org, "admin": admin, "headers": headers, "plan": plan,
            "sub_a": sub_a, "sub_b": sub_b, "cr_a": cr_a, "cr_b": cr_b}


def test_cancellation_on_last_window_day_is_refunded(api):
    """PRD: "Finalization within the plan's cancellation window — the logical
    clock being no later than `commitment_start` plus `cancellation_window_days`
    days — moves the subscription `ACTIVE → CANCELLED_IN_WINDOW` and the request
    to `REFUNDED` with `etf_amount_cents` set to zero: a full refund, no fee."

    Commitment start 2026-09-01, window 14 days: 2026-09-15 is the last
    in-window day.

    Design: Difficulty/boundary_precision_check/cancellation_window_last_day_vs_first_day_after
    """
    ctx = _monthly_cancellation_setup(api)
    set_clock("2026-09-15T00:00:00Z")
    resp = api.finalize_cancellation_request(ctx["cr_a"]["id"], SYS)
    data = validate_success(resp)
    assert data["status"] == "REFUNDED"
    assert data["etf_amount_cents"] == 0
    assert get_subscription(ctx["sub_a"]["id"])["status"] == "CANCELLED_IN_WINDOW"


def test_cancellation_first_day_after_window_on_monthly_denied(api):
    """PRD: "A `MONTHLY` plan has no ETF path at all: outside its refund window,
    finalization is rejected with `ERR_MONTHLY_NO_ETF`, and the cancellation is
    denied."

    Commitment start 2026-09-01, window 14 days: 2026-09-16 is the first
    out-of-window day, and a MONTHLY plan has no ETF path.

    Design: Difficulty/boundary_precision_check/cancellation_window_last_day_vs_first_day_after
    """
    ctx = _monthly_cancellation_setup(api, org_name="O10B")
    set_clock("2026-09-16T00:00:00Z")
    resp = api.finalize_cancellation_request(ctx["cr_b"]["id"], SYS)
    validate_error(resp, ApiErrorId.ERR_MONTHLY_NO_ETF)
    assert get_subscription(ctx["sub_b"]["id"])["status"] == "ACTIVE"


def test_seat_count_invariant_over_assign_reclaim_reassign(api):
    """PRD: "Assignment ... increments the subscription's `seats_assigned` by
    one" and PRD: "Finalization ... decrements the subscription's
    `seats_assigned` by one" and PRD: "a reclaimed seat is reusable and can be
    assigned again under exactly the same preconditions and side effects as a
    fresh assignment"

    Design: Difficulty/compensating_invariant/assign_reclaim_finalize_reassign_seat_count_invariant
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O16", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa16@o16.com", full_name="Admin 16")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="P16", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    assert sub["seats_assigned"] == 0
    seat = mint_seat_for_active_subscription(sub)
    user_a = create_end_user(org["id"], headers, email="u16a@o16.com")
    user_b = create_end_user(org["id"], headers, email="u16b@o16.com")
    assign_seat(seat["id"], user_a["id"], headers)
    assert get_subscription(sub["id"])["seats_assigned"] == 1
    api.reclaim_seat(seat["id"], headers)
    set_clock("2026-09-02T00:00:01Z")
    api.finalize_reclaim_seat(seat["id"], headers)
    assert get_subscription(sub["id"])["seats_assigned"] == 0, (
        "reclaim finalize must exactly compensate the earlier assign")
    seat_after = assign_seat(seat["id"], user_b["id"], headers)
    assert get_subscription(sub["id"])["seats_assigned"] == 1
    assert seat_after["end_user_id"] == user_b["id"]


def test_seat_count_invariant_reclaim_cancel_keeps_count(api):
    """PRD: "Inside the grace window the reclaim can be cancelled — the seat
    returns `PENDING_RECLAIM → ASSIGNED`" — the seats_assigned count, unchanged
    by the reclaim start, must also be unchanged after the cancel.

    Design: Difficulty/compensating_invariant/assign_reclaim_finalize_reassign_seat_count_invariant
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O16C", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa16c@o16.com", full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="P16C", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u16c@o16.com")
    assign_seat(seat["id"], user["id"], headers)
    assert get_subscription(sub["id"])["seats_assigned"] == 1
    api.reclaim_seat(seat["id"], headers)
    assert get_subscription(sub["id"])["seats_assigned"] == 1
    api.cancel_reclaim_seat(seat["id"], headers)
    sub_after = get_subscription(sub["id"])
    assert sub_after["seats_assigned"] == 1, (
        f"reclaim-cancel must leave seats_assigned at 1, got "
        f"{sub_after['seats_assigned']}")
    assert get_seat(seat["id"])["status"] == "ASSIGNED"


def test_asset_transfer_conserves_org_storage_attribution(api):
    """PRD: "the storage accounting re-attributes: the source owner's
    `storage_used_gb` loses the asset's size and the new owner's gains it, per
    the user-storage calculation."

    1500 MB asset: ceil(1500/1024) = 2 GB moves from source to target; the sum
    attributed to both users is conserved.

    Design: Difficulty/compensating_invariant/asset_transfer_storage_conservation_invariant
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O17", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa17@o17.com", full_name="Admin 17")
    headers = make_org_admin_headers(admin["id"])
    user_a = create_end_user(org["id"], headers, email="u17a@o17.com")
    user_b = create_end_user(org["id"], headers, email="u17b@o17.com")
    asset = create_asset(user_a["id"], headers, title="Moodboard", size_mb=1500)
    assert get_end_user(user_a["id"])["storage_used_gb"] == 2
    assert get_end_user(user_b["id"])["storage_used_gb"] == 0
    resp = api.transfer_asset(asset["id"], {"to_user_id": user_b["id"]}, headers)
    validate_success(resp)
    resp = api.accept_asset_transfer(asset["id"],
                                     make_end_user_headers(user_b["id"]))
    data = validate_success(resp)
    assert data["owner_user_id"] == user_b["id"]
    assert get_end_user(user_a["id"])["storage_used_gb"] == 0
    assert get_end_user(user_b["id"])["storage_used_gb"] == 2


def test_asset_transfer_accept_settles_asset_active_under_new_owner(api):
    """PRD: "Acceptance sets `owner_user_id` to the recipient and the status
    passes momentarily through `TRANSFERRED` before settling back to `ACTIVE`
    under the new owner"

    Design: Difficulty/compensating_invariant/asset_transfer_storage_conservation_invariant
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O17B", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa17b@o17.com", full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    user_a = create_end_user(org["id"], headers, email="u17ba@o17.com")
    user_b = create_end_user(org["id"], headers, email="u17bb@o17.com")
    asset = create_asset(user_a["id"], headers, title="Board", size_mb=2048)
    api.transfer_asset(asset["id"], {"to_user_id": user_b["id"]}, headers)
    resp = api.accept_asset_transfer(asset["id"],
                                     make_end_user_headers(user_b["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["owner_user_id"] == user_b["id"]
    assert get_asset(asset["id"])["org_id"] == org["id"]
