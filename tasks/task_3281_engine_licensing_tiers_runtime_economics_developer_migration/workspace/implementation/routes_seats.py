"""Seat subscription routes."""
from flask import Blueprint

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_INTERVAL,
    ERR_SUBSCRIPTION_OVERLAP, ERR_SEAT_CAPACITY, ERR_STALE_VERSION,
    ERR_ORG_SUSPENDED,
)
from helpers import ok, ok_list, body, new_common, parse_date, touch
from middleware import authenticate, authorize, get_org_or_404, check_org_ownership
from routes_orgs import _is_migrated

bp = Blueprint("seats", __name__)

PAID_TIERS = {"PRO", "ENTERPRISE"}


@bp.route("/orgs/<oid>/seat-subscriptions", methods=["POST"])
def create_subscription(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner", "PlatformAdmin"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    if _is_migrated(oid) or org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    tier_code = b.get("tier_code")
    if tier_code not in PAID_TIERS:
        raise_err(ERR_VALIDATION, "tier_code must be PRO or ENTERPRISE")
    seats = b.get("purchased_seats")
    if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
        raise_err(ERR_VALIDATION, "purchased_seats must be >= 1")
    start = parse_date(b.get("coverage_start"))
    end = parse_date(b.get("coverage_end"))
    if start is None or end is None or not (start < end):
        raise_err(ERR_INVALID_INTERVAL, "coverage_start must be strictly before coverage_end")
    if "expected_org_version" not in b:
        raise_err(ERR_VALIDATION, "expected_org_version is required")
    if b["expected_org_version"] != org["version"]:
        raise_err(ERR_STALE_VERSION, "Org version mismatch")
    # Overlap: half-open [start, end), same org + tier_code, non-expired subs
    for s in db.seat_subscriptions.values():
        if s["org_id"] != oid or s["tier_code"] != tier_code:
            continue
        if s["subscription_status"] == "EXPIRED":
            continue
        s2 = parse_date(s["coverage_start"]); e2 = parse_date(s["coverage_end"])
        if start < e2 and s2 < end:
            raise_err(ERR_SUBSCRIPTION_OVERLAP, "Overlapping subscription for same tier")
    ent = new_common()
    ent.update({
        "org_id": oid,
        "tier_code": tier_code,
        "purchased_seats": seats,
        "active_seats": 0,
        "available_seats": seats,
        "coverage_start": b["coverage_start"],
        "coverage_end": b["coverage_end"],
        "subscription_status": "ACTIVE",
    })
    db.seat_subscriptions[ent["id"]] = ent
    touch(org)
    return ok(ent, 201)


@bp.route("/orgs/<oid>/seat-subscriptions", methods=["GET"])
def list_subscriptions(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    from flask import request
    items = [s for s in db.seat_subscriptions.values() if s["org_id"] == oid]
    items.sort(key=lambda s: s["created_at"])
    tc = request.args.get("tier_code")
    if tc:
        items = [s for s in items if s["tier_code"] == tc]
    return ok_list(items)


def _get_sub_for_action(sid, role, uid):
    s = db.seat_subscriptions.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Subscription not found")
    if role == "OrgOwner" and uid != s["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your subscription")
    return s


from errors import ERR_FORBIDDEN_ORG


@bp.route("/seat-subscriptions/<sid>/assign", methods=["POST"])
def assign_seat(sid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    s = _get_sub_for_action(sid, role, uid)
    if s["subscription_status"] != "ACTIVE":
        raise_err(ERR_SEAT_CAPACITY, "No available seats")
    if s["available_seats"] < 1:
        raise_err(ERR_SEAT_CAPACITY, "No available seats")
    s["active_seats"] += 1
    s["available_seats"] -= 1
    if s["active_seats"] == s["purchased_seats"]:
        s["subscription_status"] = "EXHAUSTED"
    touch(s)
    return ok(s)


@bp.route("/seat-subscriptions/<sid>/release", methods=["POST"])
def release_seat(sid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    s = _get_sub_for_action(sid, role, uid)
    if s["active_seats"] < 1:
        raise_err(ERR_SEAT_CAPACITY, "No active seats to release")
    s["active_seats"] -= 1
    s["available_seats"] += 1
    if s["subscription_status"] == "EXHAUSTED" and s["active_seats"] < s["purchased_seats"]:
        s["subscription_status"] = "ACTIVE"
    touch(s)
    return ok(s)
