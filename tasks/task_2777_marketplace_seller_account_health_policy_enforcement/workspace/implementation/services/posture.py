"""The two posture dimensions and their cascades (PRD 2.5, 3.2, 3.6, 3.9)."""

from datetime import timedelta
from decimal import Decimal

import clock
import constants as C
import db
from services import calc, notify

ZERO2 = Decimal("0.00")


# --- listing cascades -------------------------------------------------------

def suppress_active_listings(seller):
    for row in db.listings_of(seller["id"]):
        if row["state"] == "ACTIVE":
            db.set_field(row, "state", "SUPPRESSED")
            db.set_field(row, "suppressed_by_suspension", True)


def remove_listings_for_ban(seller):
    for row in db.listings_of(seller["id"]):
        if row["state"] in ("ACTIVE", "SUPPRESSED"):
            db.set_field(row, "state", "REMOVED")
            db.set_field(row, "suppressed_by_suspension", False)


def restore_suppressed_listings(seller):
    for row in db.listings_of(seller["id"]):
        if row["suppressed_by_suspension"] and row["state"] == "SUPPRESSED":
            db.set_field(row, "state", "ACTIVE")
            db.set_field(row, "suppressed_by_suspension", False)


def remove_listings_for_action(seller, action, removal_scope, cited_listing_id):
    """PRD 3.6: a LISTING_REMOVAL rung removes the cited item or the whole catalogue."""
    if removal_scope == "LISTING":
        targets = [db.LISTINGS[cited_listing_id]] if cited_listing_id in db.LISTINGS else []
    else:
        targets = db.listings_of(seller["id"])
    removed = 0
    for row in targets:
        if row["state"] not in ("ACTIVE", "SUPPRESSED"):
            continue
        db.set_field(row, "state", "REMOVED")
        db.set_field(row, "removal_policy_category", action["policy_category"])
        db.set_field(row, "suppressed_by_suspension", False)
        removed += 1
    db.set_field(action, "removed_listing_count", removed)


# --- funds movement ---------------------------------------------------------

def _release_hold(seller, hold, reason):
    amount = hold["held_amount_cents"]
    db.set_field(hold, "state", "RELEASED")
    db.set_field(hold, "released_at", clock.now())
    db.set_field(hold, "release_reason", reason)
    db.set_field(seller, "held_balance_cents", seller["held_balance_cents"] - amount)
    db.set_field(seller, "available_balance_cents", seller["available_balance_cents"] + amount)
    return amount


def active_holds(seller):
    return [h for h in db.holds_of(seller["id"]) if h["state"] == "ACTIVE"]


def _sweep_to_full_hold(seller):
    """PRD 3.9: release the reserves, mint one sweeping row, zero the available balance."""
    for hold in active_holds(seller):
        _release_hold(seller, hold, "SUPERSEDED_BY_FULL_HOLD")
    swept = seller["available_balance_cents"]
    now = clock.now()
    row = db.new_row(
        "hold",
        seller_id=seller["id"],
        enforcement_action_id=None,
        hold_type="FULL_HOLD",
        reserve_basis="NONE",
        risk_tier=calc.risk_tier(seller),
        held_amount_cents=swept,
        coverage_start=now,
        coverage_end=now + timedelta(days=C.FULL_HOLD_COVERAGE_DAYS),
        state="ACTIVE",
        auto_created=True,
        created_by_user_id=None,
        released_at=None,
        release_reason=None,
        forfeited_amount_cents=0,
    )
    db.DISBURSEMENT_HOLDS[row["id"]] = row
    db.set_field(seller, "available_balance_cents", 0)
    db.set_field(seller, "held_balance_cents", swept)
    notify.emit(seller["id"], "FUNDS_HELD", "DISBURSEMENT_HOLD", row["id"],
                amount_cents=swept)
    return row


def _release_all(seller, reason, aggregate):
    holds = active_holds(seller)
    released = []
    total = 0
    for hold in holds:
        total += _release_hold(seller, hold, reason)
        released.append(hold)
    if not released:
        return
    if aggregate:
        anchor = None
        for hold in released:
            if hold["hold_type"] == "FULL_HOLD":
                anchor = hold
                break
        if anchor is None:
            anchor = released[0]
        notify.emit(seller["id"], "FUNDS_RELEASED", "DISBURSEMENT_HOLD", anchor["id"],
                    amount_cents=total)
    else:
        for hold in released:
            notify.emit(seller["id"], "FUNDS_RELEASED", "DISBURSEMENT_HOLD", hold["id"],
                        amount_cents=hold["held_amount_cents"])


# --- the three recompute steps ---------------------------------------------

def recompute_balance(seller):
    balance = calc.decayed_balance(db.actions_of(seller["id"]), clock.now())
    db.set_field(seller, "severity_points_balance", balance)


def enforcement_target(seller):
    if seller.get("ban_reason"):
        return "BANNED"
    for action in db.actions_of(seller["id"]):
        if (action["action_type"] == "ACCOUNT_SUSPENSION"
                and action["state"] in C.ACTION_LIVE_STATES):
            return "SUSPENDED"
    balance = Decimal(seller["severity_points_balance"])
    if balance >= C.LADDER_SUSPEND_POINTS:
        return "SUSPENDED"
    if balance >= C.LADDER_RESTRICT_POINTS:
        return "RESTRICTED"
    if balance > ZERO2 or seller.get("registration_risk_flag"):
        return "WATCHLIST"
    return "ACTIVE"


def disbursement_target(seller):
    if seller["enforcement_state"] in ("SUSPENDED", "BANNED"):
        return "FULL_HOLD"
    if seller["enforcement_state"] in ("WATCHLIST", "RESTRICTED"):
        return "RESERVE_HELD"
    for violation in db.violations_of(seller["id"]):
        if violation["state"] == "UNDER_INVESTIGATION":
            return "RESERVE_HELD"
    return "NORMAL"


def apply_enforcement(seller, force_suspension_cascade=False):
    previous = seller["enforcement_state"]
    target = enforcement_target(seller)
    db.set_field(seller, "enforcement_state", target)
    if target == "SUSPENDED" and (previous != "SUSPENDED" or force_suspension_cascade):
        suppress_active_listings(seller)
    if target == "BANNED" and previous != "BANNED":
        remove_listings_for_ban(seller)
    if previous == "SUSPENDED" and target not in ("SUSPENDED", "BANNED"):
        restore_suppressed_listings(seller)
    return target


def apply_disbursement(seller, release_reason=None):
    previous = seller["disbursement_state"]
    target = disbursement_target(seller)
    db.set_field(seller, "disbursement_state", target)
    if target == "FULL_HOLD" and previous != "FULL_HOLD":
        _sweep_to_full_hold(seller)
    elif previous == "FULL_HOLD" and target != "FULL_HOLD":
        _release_all(seller, release_reason or "APPEAL_GRANTED", aggregate=True)
    elif previous == "RESERVE_HELD" and target == "NORMAL":
        _release_all(seller, release_reason or "INVESTIGATION_CLOSED", aggregate=False)
    return target


def recompute(seller, release_reason=None, recompute_points=True,
              force_suspension_cascade=False):
    """The fixed three-step order of PRD 2.5."""
    if recompute_points:
        recompute_balance(seller)
    apply_enforcement(seller, force_suspension_cascade=force_suspension_cascade)
    apply_disbursement(seller, release_reason=release_reason)
