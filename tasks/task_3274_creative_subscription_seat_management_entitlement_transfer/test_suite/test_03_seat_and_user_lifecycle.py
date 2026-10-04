"""Seat lifecycle loop and end-user branching tests (depth queue A)."""
import pytest

from test_helpers import (
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_active_subscription,
    create_end_user,
    mint_seat_for_active_subscription,
    assign_seat,
    get_seat,
    get_subscription,
    get_end_user,
    set_clock,
    setup_assigned_seat,
    validate_success,
    make_org_admin_headers,
)


def _seat_cycle_setup(api, org_name="O4"):
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=org_name, org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email=f"oa@{org_name}.com",
                         full_name="Admin Four")
    admin_headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code=f"{org_name}-P", segment="TEAM",
                       billing_model="MONTHLY", monthly_price_cents=3000,
                       annual_monthly_price_cents=3000, storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], admin_headers, email=f"u@{org_name}.com")
    return {"org": org, "admin": admin, "admin_headers": admin_headers,
            "plan": plan, "subscription": sub, "seat": seat, "user": user}


def test_seat_reclaim_cancel_returns_to_assigned(api):
    """PRD: "Inside the grace window the reclaim can be cancelled — the seat
    returns `PENDING_RECLAIM → ASSIGNED`, `pending_reclaim_not_before` clears to
    null, and the suspended entitlement reactivates."

    Design: Difficulty/non_linear_state_machine/seat_assign_reclaim_cancel_reassign_cycle
    """
    ctx = _seat_cycle_setup(api)
    headers = ctx["admin_headers"]
    seat = assign_seat(ctx["seat"]["id"], ctx["user"]["id"], headers)
    resp = api.reclaim_seat(seat["id"], headers)
    seat = validate_success(resp)
    assert seat["status"] == "PENDING_RECLAIM"
    assert seat["pending_reclaim_not_before"] is not None
    resp = api.cancel_reclaim_seat(seat["id"], headers)
    seat = validate_success(resp)
    assert seat["status"] == "ASSIGNED"
    assert seat["pending_reclaim_not_before"] is None
    assert seat["end_user_id"] == ctx["user"]["id"]


def test_seat_full_reclaim_finalize_reassign_cycle(api):
    """PRD: "`RECLAIMED` is not terminal — a reclaimed seat is reusable and can
    be assigned again under exactly the same preconditions and side effects as
    a fresh assignment, including the creation of a fresh entitlement."

    Design: Difficulty/non_linear_state_machine/seat_assign_reclaim_cancel_reassign_cycle
    """
    ctx = _seat_cycle_setup(api, org_name="O4C")
    headers = ctx["admin_headers"]
    seat = assign_seat(ctx["seat"]["id"], ctx["user"]["id"], headers)
    api.reclaim_seat(seat["id"], headers)
    set_clock("2026-09-02T00:00:01Z")
    resp = api.finalize_reclaim_seat(seat["id"], headers)
    seat = validate_success(resp)
    assert seat["status"] == "RECLAIMED"
    assert seat["end_user_id"] is None
    # RECLAIMED -> ASSIGNED reassign allowed (cyclic)
    resp = api.assign_seat(seat["id"], {"end_user_id": ctx["user"]["id"]},
                           headers)
    seat = validate_success(resp)
    assert seat["status"] == "ASSIGNED"
    assert seat["end_user_id"] == ctx["user"]["id"]


def test_enduser_reactivation_rolls_back_pending_reclaim(api):
    """PRD: "Reactivation (`DEACTIVATED → ACTIVE`) rolls back any of those
    deactivation-initiated reclaims whose grace has not yet lapsed — the seats
    return to `ASSIGNED` and their entitlements resume `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/enduser_deactivate_reactivate_and_departed_branching
    """
    ctx = _seat_cycle_setup(api, org_name="O5R")
    headers = ctx["admin_headers"]
    seat = assign_seat(ctx["seat"]["id"], ctx["user"]["id"], headers)
    api.deactivate_end_user(ctx["user"]["id"], headers)
    assert get_seat(seat["id"])["status"] == "PENDING_RECLAIM"
    assert get_end_user(ctx["user"]["id"])["status"] == "DEACTIVATED"
    resp = api.reactivate_end_user(ctx["user"]["id"], headers)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    seat_after = get_seat(seat["id"])
    assert seat_after["status"] == "ASSIGNED", (
        f"Expected seat ASSIGNED after reactivation, got {seat_after['status']}")
    assert seat_after["end_user_id"] == ctx["user"]["id"]


def test_enduser_deactivate_then_departed_branch(api):
    """PRD: "Deactivating a user (`ACTIVE → DEACTIVATED`, an `OrgAdmin` action
    requiring the organization to be `ACTIVE`) immediately places every seat
    `ASSIGNED` to that user into `PENDING_RECLAIM` with the standard 24-hour
    grace" and "Marking the user `DEPARTED` is the point of no return: every
    seat still in `PENDING_RECLAIM` for this user is finalized immediately
    regardless of remaining grace, becoming `RECLAIMED`"

    Design: Difficulty/non_linear_state_machine/enduser_deactivate_reactivate_and_departed_branching
    """
    ctx = _seat_cycle_setup(api, org_name="O5D")
    headers = ctx["admin_headers"]
    seat = assign_seat(ctx["seat"]["id"], ctx["user"]["id"], headers)
    api.deactivate_end_user(ctx["user"]["id"], headers)
    assert get_seat(seat["id"])["status"] == "PENDING_RECLAIM"
    resp = api.mark_departed_end_user(ctx["user"]["id"], headers)
    data = validate_success(resp)
    assert data["status"] == "DEPARTED"
    seat_after = get_seat(seat["id"])
    assert seat_after["status"] == "RECLAIMED"
    assert seat_after["end_user_id"] is None
    assert get_subscription(ctx["subscription"]["id"])["seats_assigned"] == 0
