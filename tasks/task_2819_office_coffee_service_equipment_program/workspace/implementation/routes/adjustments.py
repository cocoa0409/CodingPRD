"""Green coffee repricing and the negotiation cycle (PRD 3.9).

The proposal is computed end to end from the account's own baseline and the market
quote; only the customer may accept or dispute, and only billing may revise.
"""
from datetime import timedelta

from flask import Blueprint

import calc
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_CUSTOMER_CONTACT,
                   authenticate, require_account_contact)
from envelope import created, ok
from errors import ApiError
from store import bump, db, insert, now

bp = Blueprint("adjustments", __name__)

READ_ROLES = (ROLE_BILLING_SPECIALIST, ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT)
DISPOSITIONS = ("ACCEPT", "DISPUTE")
RESPONDED_STATUSES = ("ACCEPTED", "DISPUTED")


@bp.post("/ocs/price-adjustments")
def propose_adjustment():
    authenticate((ROLE_BILLING_SPECIALIST,))
    fields = shape.fields()
    account_id = fields.string("account_id", min_len=1)
    effective_at = fields.instant("effective_at")

    account = lookup.account(account_id)
    protection = account.get("price_protection_until")
    if protection is not None and protection > now():
        raise ApiError("ERR_PRICE_PROTECTION_ACTIVE",
                       "The account is still inside its price-protection window.")

    baseline = account["green_index_baseline_micros"]
    current = db.green_index_micros
    movement = calc.movement_bps(current, baseline)
    if abs(movement) < calc.MOVEMENT_THRESHOLD_BPS:
        raise ApiError("ERR_INDEX_MOVEMENT_BELOW_THRESHOLD",
                       "A movement of %d bps is below the %d bps threshold."
                       % (movement, calc.MOVEMENT_THRESHOLD_BPS))

    row = insert(db.price_adjustments, {
        "account_id": account["id"],
        "index_baseline_micros": baseline,
        "index_current_micros": current,
        "movement_bps": movement,
        "adjustment_pct_bps": calc.pass_through_bps(movement),
        "adj_status": "PROPOSED",
        "dispute_reason": None,
        "revision_count": 0,
        "effective_at": effective_at,
        "accepted_at": None,
    })
    # Nothing on the account changes until the customer accepts.
    return created(serializers.price_adjustment(row))


@bp.get("/ocs/price-adjustments")
def list_adjustments():
    authenticate(READ_ROLES)
    rows = lookup.eq_filter(list(db.price_adjustments.values()), "account_id")
    rows = lookup.eq_filter(rows, "adj_status")
    return lookup.listing(rows, serializers.price_adjustment)


@bp.get("/ocs/price-adjustments/<adjustment_id>")
def read_adjustment(adjustment_id):
    authenticate(READ_ROLES)
    return ok(serializers.price_adjustment(lookup.price_adjustment(adjustment_id)))


@bp.post("/ocs/price-adjustments/<adjustment_id>/respond")
def respond_to_adjustment(adjustment_id):
    actor = authenticate((ROLE_CUSTOMER_CONTACT,))
    fields = shape.fields()
    disposition = fields.enum("disposition", DISPOSITIONS)
    dispute_reason = fields.string("dispute_reason", required=False, min_len=1)

    adjustment = lookup.price_adjustment(adjustment_id)
    require_account_contact(actor, adjustment["account_id"])

    if adjustment["adj_status"] in RESPONDED_STATUSES:
        raise ApiError("ERR_ADJUSTMENT_STATE_INVALID",
                       "This adjustment has already been answered (%s)."
                       % adjustment["adj_status"])
    if adjustment["adj_status"] == "DEFERRED":
        # Its own code, because the reason is worth telling the customer.
        raise ApiError("ERR_ADJUSTMENT_DEFERRED",
                       "The account is AT_RISK and the negotiation is frozen.")
    if disposition == "DISPUTE" and dispute_reason is None:
        raise ApiError("ERR_MISSING_TRANSITION_FIELD",
                       "dispute_reason is required to dispute an adjustment.")

    if disposition == "DISPUTE":
        adjustment["adj_status"] = "DISPUTED"
        adjustment["dispute_reason"] = dispute_reason
        bump(adjustment)
        return ok(serializers.price_adjustment(adjustment))

    adjustment["adj_status"] = "ACCEPTED"
    adjustment["accepted_at"] = now()
    bump(adjustment)
    account = db.accounts.get(adjustment["account_id"])
    if account is not None:
        # Absolute against the unmodified baseline of 10000, never compounded.
        factor = 10000 + adjustment["adjustment_pct_bps"]
        if factor < calc.FACTOR_FLOOR_BPS:
            factor = calc.FACTOR_FLOOR_BPS
        account["green_price_factor_bps"] = factor
        # Re-based, so the next proposal measures movement from here.
        account["green_index_baseline_micros"] = adjustment["index_current_micros"]
        account["price_protection_until"] = now() + timedelta(
            days=account["price_protection_days"])
        bump(account)
    return ok(serializers.price_adjustment(adjustment))


@bp.post("/ocs/price-adjustments/<adjustment_id>/revise")
def revise_adjustment(adjustment_id):
    authenticate((ROLE_BILLING_SPECIALIST,))
    fields = shape.fields()
    revised = fields.integer("revised_adjustment_pct_bps")

    adjustment = lookup.price_adjustment(adjustment_id)
    if adjustment["adj_status"] != "DISPUTED":
        raise ApiError("ERR_ADJUSTMENT_STATE_INVALID",
                       "Only a disputed adjustment may be revised (%s)."
                       % adjustment["adj_status"])
    # The revised figure may only move TOWARD the customer.
    current = adjustment["adjustment_pct_bps"]
    low, high = (0, current) if current >= 0 else (current, 0)
    if revised < low or revised > high:
        raise ApiError("ERR_REVISION_OUT_OF_BOUNDS",
                       "The revised figure must lie between %d and %d bps." % (low, high))

    adjustment["adjustment_pct_bps"] = revised
    adjustment["revision_count"] = adjustment["revision_count"] + 1
    adjustment["adj_status"] = "PROPOSED"
    bump(adjustment)
    return ok(serializers.price_adjustment(adjustment))
