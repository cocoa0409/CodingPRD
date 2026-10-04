"""Shared service helpers: payload parsing, enum checks, ledger recomputation."""
from datetime import datetime, timezone

from envelope import ApiError, invalid_request, value_rejected
from catalog import ENUMS
from store import DB, parse_dt, to_ms
from calc import bps_floor, day_gap


def body():
    from flask import request
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require(data, names):
    """ERR_INVALID_REQUEST when a required body field is absent (None counts as absent)."""
    for name in names:
        if name not in data or data.get(name) is None:
            raise invalid_request("Field '%s' is required." % name)
    return data


def as_int(data, name, default=None, minimum=None):
    if name not in data or data.get(name) is None:
        return default
    raw = data.get(name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        if isinstance(raw, str) and raw.lstrip("-").isdigit():
            raw = int(raw)
        elif isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        else:
            raise invalid_request("Field '%s' must be an integer." % name)
    if minimum is not None and raw < minimum:
        raise invalid_request("Field '%s' must be at least %d." % (name, minimum))
    return raw


def enum_value(data, name, key, required=True):
    raw = data.get(name)
    if raw is None:
        if required:
            raise invalid_request("Field '%s' is required." % name)
        return None
    if raw not in ENUMS[key]:
        raise value_rejected("Field '%s' carries an undeclared value." % name)
    return raw


def check_enum_optional(data, name, key):
    raw = data.get(name)
    if raw is None:
        return None
    if raw not in ENUMS[key]:
        raise value_rejected("Field '%s' carries an undeclared value." % name)
    return raw


def body_datetime(data, name, required=True):
    raw = data.get(name)
    if raw is None:
        if required:
            raise invalid_request("Field '%s' is required." % name)
        return None
    dt = parse_dt(raw)
    if dt is None:
        raise invalid_request("Field '%s' is not a valid ISO 8601 instant." % name)
    return to_ms(dt)


# ---------------------------------------------------------------------------
# ledger maintenance
# ---------------------------------------------------------------------------

def recompute_offering_shares(offering):
    subs = [s for s in DB.subscriptions.values() if s["offering_id"] == offering["id"]]
    accepted = sum(int(s.get("accepted_shares") or 0) for s in subs
                   if s["status"] in ("SUBSCRIBED", "REALLOCATED"))
    reserved = sum(int(s.get("requested_shares") or 0) for s in subs
                   if s["status"] == "WAITLISTED")
    offering["accepted_shares"] = accepted
    offering["reserved_shares"] = reserved
    offering["unsubscribed_shares"] = int(offering["total_shares"]) - accepted - reserved
    return offering


def recompute_offering_cash(offering):
    subs = [s for s in DB.subscriptions.values() if s["offering_id"] == offering["id"]]
    collected = sum(int(s.get("collected_subscription_cents") or 0) for s in subs)
    refunded = sum(int(s.get("refunded_cents") or 0) for s in subs)
    offering["cash_ledger_cents"] = collected - refunded
    return offering


def policy_in_force(offering_id):
    return any(p["status"] == "FORCE" for p in DB.insurance_policies.values()
               if p["offering_id"] == offering_id)


def open_transfer_order(offering_id):
    return any(o["status"] == "OPEN" for o in DB.transfer_orders.values()
               if o["offering_id"] == offering_id)


def evaluate_lot(offering, artwork_row, lot):
    """The five hard gates, in order, first failure short-circuits (§1.3)."""
    allowed = True
    if lot["lot_type"] not in ("STORAGE", "INSURANCE", "CONSERVATION"):
        allowed = False
    elif offering["status"] not in ("ALLOCATED", "HELD"):
        allowed = False
    elif not policy_in_force(offering["id"]):
        allowed = False
    elif open_transfer_order(offering["id"]):
        allowed = False
    elif offering.get("holding_clock_started_at") is None:
        allowed = False
    else:
        incurred = parse_dt(lot["incurred_on"])
        started = parse_dt(offering["holding_clock_started_at"])
        if incurred is None or started is None or incurred < started:
            allowed = False
    lot["pass_through_allowed"] = allowed
    lot["pass_through_amount_cents"] = (
        bps_floor(lot["cost_amount_cents"], offering["cost_pass_through_bps"])
        if allowed else 0)
    return lot


def recompute_lots(offering):
    artwork_row = DB.artworks.get(offering["artwork_id"])
    total = 0
    for lot in DB.lots.values():
        if lot["offering_id"] == offering["id"]:
            evaluate_lot(offering, artwork_row, lot)
            total += int(lot.get("pass_through_amount_cents") or 0)
    offering["custody_cost_ledger_cents"] = total
    return total


def recompute_custody_cost_ledger(offering):
    total = sum(int(l.get("pass_through_amount_cents") or 0) for l in DB.lots.values()
                if l["offering_id"] == offering["id"])
    offering["custody_cost_ledger_cents"] = total
    return total


def investor_holding(offering_id, investor_id):
    return sum(int(s.get("accepted_shares") or 0) for s in DB.subscriptions.values()
               if s["offering_id"] == offering_id and s["investor_id"] == investor_id)


def refund_subscription(sub):
    previous = int(sub.get("refunded_cents") or 0)
    now_refunded = int(sub.get("collected_subscription_cents") or 0)
    sub["refunded_cents"] = now_refunded
    delta = now_refunded - previous
    if delta > 0:
        from svc_sale import release_investor_funds
        release_investor_funds(delta)


def offering_of(row):
    return DB.offerings.get(row.get("offering_id"))