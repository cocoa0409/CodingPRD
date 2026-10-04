"""Memberships: enrolment, billing cycles, freezing, cancellation and expiry."""

from core import (
    DAYS_PER_CYCLE,
    FREEZE_ANNUAL_CAP_DAYS,
    MEMBERSHIP_EXPIRY_GRACE_DAYS,
    add_days,
    add_months,
    fail,
    now,
)
from commons import mint, refresh_client, require_gate, touch
from store import (
    CLASS_PACKS,
    CLIENTS,
    MEMBERSHIPS,
    STUDIOS,
    SUBSCRIPTIONS,
)

import calc
import lifecycle


def assert_operating(studio):
    if studio.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_STUDIO_NOT_OPERATING")
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None and subscription.get("status") in (
        "SUSPENDED",
        "CANCELLED",
    ):
        fail("ERR_SUBSCRIPTION_INACTIVE")


def membership_or_404(membership_id):
    membership = MEMBERSHIPS.get(membership_id)
    if membership is None:
        fail("ERR_MEMBERSHIP_NOT_FOUND")
    return membership


def create_membership(body):
    studio = STUDIOS.get(body.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    require_gate(studio, "staff_payroll")
    assert_operating(studio)

    anchor = int(body.get("billing_anchor_day", 1))
    if not (1 <= anchor <= 28):
        fail("ERR_INVALID_STATE", "billing_anchor_day must be between 1 and 28.", 409)

    auto_renew = body.get("auto_renew")
    if auto_renew is None:
        auto_renew = True

    next_billing = _anchor_from(anchor)
    membership = mint(
        MEMBERSHIPS,
        {
            "studio_id": studio["id"],
            "client_id": client["id"],
            "plan_name": body.get("plan_name"),
            "monthly_fee_cents": int(body.get("monthly_fee_cents", 0)),
            "included_credits_per_cycle": int(body.get("included_credits_per_cycle", 0)),
            "minimum_term_months": int(body.get("minimum_term_months", 0)),
            "freeze_allowed": bool(body.get("freeze_allowed", False)),
            "freeze_max_days_per_cycle": int(body.get("freeze_max_days_per_cycle", 0)),
            "billing_anchor_day": anchor,
            "current_period_index": 0,
            "next_billing_at": next_billing,
            "auto_renew": bool(auto_renew),
            "freeze_start_at": None,
            "freeze_resume_at": None,
            "freeze_days_used": 0,
            "prorated_fee_cents": 0,
            "open_balance_cents": 0,
            "status": "ACTIVE",
            "_credits_remaining": int(body.get("included_credits_per_cycle", 0)),
            "_planned_freeze_days": 0,
        },
    )
    touch(client)
    refresh_client(client)
    return membership


def _anchor_from(anchor):
    current = now()
    try:
        candidate = current.replace(day=anchor)
    except ValueError:
        candidate = current
    return candidate


def advance_cycle(membership, body):
    days = body.get("advance_days")
    if days not in (None, ""):
        from core import advance_clock as move_clock

        move_clock(days=int(days))
    outcome = body.get("outcome")
    if outcome not in ("CHARGED", "EARLY_CHARGED"):
        fail("ERR_INVALID_STATE", "outcome must be CHARGED or EARLY_CHARGED.", 409)

    status = membership.get("status")
    if status == "EXPIRED":
        fail("ERR_ALREADY_TERMINAL")
    if status == "CANCELLED":
        fail("ERR_INVALID_STATE", "A cancelled membership does not advance.", 409)

    if status == "FROZEN":
        membership["next_billing_at"] = add_months(membership.get("next_billing_at"), 1)
        touch(membership)
        return membership

    if membership.get("auto_renew") is False:
        membership["status"] = "LAPSED"
        touch(membership)
        return membership

    old_due = membership.get("next_billing_at")
    membership["current_period_index"] = membership.get("current_period_index", 0) + 1
    membership["next_billing_at"] = add_months(old_due, 1)
    membership["_credits_remaining"] = membership.get("_credits_remaining", 0) + membership.get(
        "included_credits_per_cycle", 0
    )
    membership["open_balance_cents"] = membership.get(
        "open_balance_cents", 0
    ) + membership.get("monthly_fee_cents", 0)

    if membership.get("status") == "PENDING":
        membership["status"] = "ACTIVE"
    elif membership.get("status") == "PAST_DUE":
        membership["status"] = "ACTIVE"

    if outcome == "CHARGED":
        test_due = membership["next_billing_at"]
    else:
        test_due = old_due

    if test_due is not None and now() >= test_due:
        membership["open_balance_cents"] += (
            membership.get("monthly_fee_cents", 0) * 10
        ) // 100
        membership["status"] = "PAST_DUE"

    touch(membership)
    return membership


def freeze(membership, body):
    if membership.get("status") not in ("ACTIVE", "PAST_DUE"):
        fail("ERR_INVALID_STATE", "The membership may not be frozen from this state.", 409)
    if not membership.get("freeze_allowed"):
        fail("ERR_FREEZE_CAP_EXCEEDED", "Freezing is not allowed on this plan.")
    freeze_days = int(body.get("freeze_days", 0))
    if freeze_days <= 0:
        fail("ERR_FREEZE_CAP_EXCEEDED")
    planned = freeze_days
    prorated, counted_days = calc.freeze_proration(
        membership.get("monthly_fee_cents", 0),
        planned,
        planned,
        membership.get("freeze_max_days_per_cycle", 0),
    )
    if membership.get("freeze_days_used", 0) + counted_days > FREEZE_ANNUAL_CAP_DAYS:
        fail("ERR_FREEZE_CAP_EXCEEDED")
    membership["status"] = "FROZEN"
    membership["freeze_start_at"] = now()
    membership["freeze_resume_at"] = add_days(now(), freeze_days)
    membership["_planned_freeze_days"] = planned
    membership["prorated_fee_cents"] = prorated
    membership["freeze_days_used"] = membership.get("freeze_days_used", 0) + counted_days
    membership["_freeze_counted"] = counted_days
    touch(membership)
    _hold_client_packs(membership, frozen=True)
    return membership


def unfreeze(membership, body=None):
    if membership.get("status") != "FROZEN":
        fail("ERR_INVALID_STATE", "Only a frozen membership may unfreeze.", 409)
    started = membership.get("freeze_start_at")
    if started is not None and now() < started:
        fail("ERR_INVALID_STATE", "The freeze has not started yet.", 409)
    elapsed = 0
    if started is not None:
        elapsed = max(0, (now() - started).days)
    planned = membership.get("_planned_freeze_days", elapsed)
    prorated, counted = calc.freeze_proration(
        membership.get("monthly_fee_cents", 0),
        elapsed,
        planned,
        membership.get("freeze_max_days_per_cycle", 0),
    )
    previous = membership.get("_freeze_counted", 0)
    delta = counted - previous
    if delta > 0 and membership.get("freeze_days_used", 0) + delta > FREEZE_ANNUAL_CAP_DAYS:
        fail("ERR_FREEZE_CAP_EXCEEDED")
    membership["freeze_days_used"] = membership.get("freeze_days_used", 0) + max(0, delta)
    membership["prorated_fee_cents"] = prorated
    membership["_freeze_counted"] = counted
    membership["status"] = "ACTIVE"
    membership["freeze_start_at"] = None
    membership["freeze_resume_at"] = None
    touch(membership)
    _hold_client_packs(membership, frozen=False)
    return membership


def cancel_membership(membership, body):
    if membership.get("status") not in ("ACTIVE", "FROZEN", "PAST_DUE", "LAPSED"):
        fail("ERR_INVALID_STATE", "The membership may not be cancelled from this state.", 409)
    if membership.get("current_period_index", 0) < membership.get("minimum_term_months", 0):
        if not body.get("fee_payment_ref"):
            fail("ERR_EARLY_TERMINATION_FEE_REQUIRED")
    membership["status"] = "CANCELLED"
    touch(membership)
    return membership


def _hold_client_packs(membership, frozen):
    """Freezing a client's concurrent membership holds their pack expiry clock."""
    for pack in CLASS_PACKS.values():
        if pack.get("client_id") != membership.get("client_id"):
            continue
        if pack.get("studio_id") != membership.get("studio_id"):
            continue
        if frozen and pack.get("status") == "ACTIVE":
            pack["status"] = "FROZEN"
            touch(pack)
        elif not frozen and pack.get("status") == "FROZEN":
            pack["status"] = "ACTIVE"
            touch(pack)


def membership_clock_transitions():
    for membership in list(MEMBERSHIPS.values()):
        if membership.get("status") in ("CANCELLED", "LAPSED"):
            due = membership.get("next_billing_at")
            if due is not None and now() > add_days(due, MEMBERSHIP_EXPIRY_GRACE_DAYS):
                membership["status"] = "EXPIRED"
                touch(membership)