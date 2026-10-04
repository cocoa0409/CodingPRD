"""Checks, order lines, PPV events, promo rules."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from errors import invalid_request
from util import (success, list_response, auth, body, require, req_int,
                  req_str, parse_dt, now_ts, bump)
import services
from util import serialize, serialize_list

bp = Blueprint("checks", __name__)

READ_CHECKS = ["PlatformAdmin", "VenueManager", "Server"]
READ_PROMOS = ["PlatformAdmin", "VenueManager", "Server"]


def get_check_or_404(check_id):
    c = db.checks.get(check_id)
    if c is None:
        raise errors.not_found()
    return c


def get_line_or_404(line_id):
    l = db.order_lines.get(line_id)
    if l is None:
        raise errors.not_found()
    return l


# ---------------------------------------------------------------- checks

@bp.post("/api/checks")
def create_check():
    auth(["Server"])
    data = body()
    venue_id = require(data, "venue_id")
    if venue_id not in db.venues:
        raise errors.not_found()
    guest_id = require(data, "guest_id")
    if guest_id not in db.guests:
        raise errors.guest_not_found()
    party_size = require(data, "party_size")
    if isinstance(party_size, bool) or not isinstance(party_size, int):
        raise invalid_request("party_size must be an integer")
    if party_size <= 0:
        raise errors.quantity_invalid("party_size must be a positive integer")
    guest_count = data.get("guest_count", party_size)
    if isinstance(guest_count, bool) or not isinstance(guest_count, int):
        raise invalid_request("guest_count must be an integer")
    kind = data.get("kind", "REGULAR")
    if kind not in ("REGULAR", "PPV"):
        raise invalid_request("kind must be REGULAR or PPV")
    event_id = data.get("event_id")
    if kind == "PPV":
        if not event_id:
            raise errors.ppv_requires_event()
        event = db.events.get(event_id)
        if event is None:
            raise errors.event_not_found()
        if event["kind"] != "PPV":
            raise errors.ppv_requires_event()
    elif event_id is not None:
        if event_id not in db.events:
            raise errors.event_not_found()

    ts = now_ts()
    check = {
        "id": services.new_id(), "venue_id": venue_id, "guest_id": guest_id,
        "party_size": party_size, "guest_count": guest_count,
        "event_id": event_id, "kind": kind, "status": "OPEN",
        "subtotal_cents": 0, "tax_cents": 0, "total_cents": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.checks[check["id"]] = check
    if kind == "PPV" and event_id:
        services.recompute_ppv_posture(venue_id, event_id)
    return success(serialize(check), code=201)


@bp.get("/api/checks/<check_id>")
def get_check(check_id):
    auth(READ_CHECKS)
    return success(serialize(get_check_or_404(check_id)))


@bp.get("/api/venues/<venue_id>/checks")
def list_venue_checks(venue_id):
    auth(READ_CHECKS)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([c for c in db.checks.values() if c["venue_id"] == venue_id],
                   key=lambda c: c["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(serialize_list(items))


@bp.get("/api/checks")
def list_checks():
    auth(READ_CHECKS)
    items = sorted(db.checks.values(), key=lambda c: c["created_at"])
    venue_id = request.args.get("venue_id")
    guest_id = request.args.get("guest_id")
    event_id = request.args.get("event_id")
    status = request.args.get("status")
    if venue_id is not None:
        items = [c for c in items if c["venue_id"] == venue_id]
    if guest_id is not None:
        items = [c for c in items if c["guest_id"] == guest_id]
    if event_id is not None:
        items = [c for c in items if c.get("event_id") == event_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(serialize_list(items))


@bp.get("/api/checks/<check_id>/order-lines")
def list_check_order_lines(check_id):
    auth(READ_CHECKS)
    get_check_or_404(check_id)
    items = sorted([l for l in db.order_lines.values()
                    if l["check_id"] == check_id],
                   key=lambda l: l["created_at"])
    return list_response(serialize_list(items))


# ---------------------------------------------------------------- order lines

@bp.post("/api/checks/<check_id>/order-lines")
def add_order_line(check_id):
    auth(["Server"])
    check = get_check_or_404(check_id)
    if check["status"] != "OPEN":
        raise errors.invalid_state("Check is not OPEN")
    data = body()
    kind = require(data, "kind")
    if kind not in ("TRADITIONAL", "BONELESS"):
        raise invalid_request("kind must be TRADITIONAL or BONELESS")
    portion_count = require(data, "portion_count")
    if isinstance(portion_count, bool) or not isinstance(portion_count, int):
        raise invalid_request("portion_count must be an integer")
    if portion_count <= 0:
        raise errors.quantity_invalid("portion_count must be a positive integer")

    unit, line_total = services.line_pricing(check, kind, portion_count)
    ts = now_ts()
    line = {
        "id": services.new_id(), "check_id": check_id, "kind": kind,
        "portion_count": portion_count, "unit_price_cents": unit,
        "line_total_cents": line_total, "status": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.order_lines[line["id"]] = line
    services.recompute_check_subtotal(check)
    return success(serialize(line), code=201)


@bp.get("/api/order-lines/<line_id>")
def get_order_line(line_id):
    auth(READ_CHECKS)
    return success(serialize(get_line_or_404(line_id)))


@bp.post("/api/order-lines/<line_id>/void")
def void_order_line(line_id):
    auth(["Server"])
    line = get_line_or_404(line_id)
    check = db.checks[line["check_id"]]
    if check["status"] != "OPEN":
        raise errors.invalid_state("Parent check is not OPEN")
    if line["status"] != "OPEN":
        raise errors.invalid_state("Order line is not OPEN")
    line["status"] = "VOID"
    bump(line)
    services.recompute_check_subtotal(check)
    return success(serialize(line))


# ---------------------------------------------------------------- settle / void

@bp.post("/api/checks/<check_id>/settle")
def settle_check(check_id):
    auth(["Server"])
    check = get_check_or_404(check_id)
    if check["status"] != "OPEN":
        raise errors.invalid_state("Check is not OPEN")
    open_lines = [l for l in db.order_lines.values()
                  if l["check_id"] == check_id and l["status"] == "OPEN"]
    if not open_lines and check["kind"] != "PPV":
        raise errors.invalid_state(
            "Check must have at least one OPEN order line or be PPV")

    services.recompute_check_subtotal(check)
    subtotal = check["subtotal_cents"]
    tax = int((Decimal(subtotal) * Decimal("0.05")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    cover = services.cover_charge(check)
    check["tax_cents"] = tax
    check["total_cents"] = subtotal + tax + cover
    check["status"] = "SETTLED"
    check["_settled_at"] = db.now()
    bump(check)
    if check["kind"] == "PPV" and check.get("event_id"):
        services.recompute_ppv_posture(check["venue_id"], check["event_id"])
    return success(serialize(check))


@bp.post("/api/checks/<check_id>/void")
def void_check(check_id):
    auth(["VenueManager"])
    check = get_check_or_404(check_id)
    if check["status"] != "OPEN":
        raise errors.invalid_state("Check is not OPEN")
    open_lines = [l for l in db.order_lines.values()
                  if l["check_id"] == check_id and l["status"] != "VOID"]
    if open_lines:
        raise errors.invalid_state("All order lines must be VOID to void the check")
    check["status"] = "VOIDED"
    check["subtotal_cents"] = 0
    check["tax_cents"] = 0
    check["total_cents"] = 0
    bump(check)
    if check["kind"] == "PPV" and check.get("event_id"):
        services.recompute_ppv_posture(check["venue_id"], check["event_id"])
    return success(serialize(check))


# ---------------------------------------------------------------- PPV events

@bp.post("/api/venues/<venue_id>/ppv-events")
def create_ppv_event(venue_id):
    auth(["VenueManager"])
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.not_found()
    data = body()
    event_id = require(data, "event_id")
    event = db.events.get(event_id)
    if event is None:
        raise errors.event_not_found()
    if event["kind"] != "PPV":
        raise errors.ppv_requires_event("event_id must reference a PPV event")
    lic = services.find_license(venue_id, event["league"])
    if lic is None or lic["status"] != "ACTIVE":
        raise errors.license_not_active()
    commercial_fee = req_int(data, "commercial_fee_cents", minimum=0)
    cover_charge = req_int(data, "cover_charge_cents", minimum=0)
    total_guests = services.guest_count_total_for_event(venue_id, event_id)
    posture = int(total_guests * (commercial_fee * 1.20 + cover_charge))
    ts = now_ts()
    ppv = {
        "id": services.new_id(), "venue_id": venue_id, "event_id": event_id,
        "commercial_fee_cents": commercial_fee,
        "cover_charge_cents": cover_charge,
        "capacity_posture_cents": posture,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.ppv_events[ppv["id"]] = ppv
    return success(serialize(ppv), code=201)


@bp.get("/api/ppv-events/<ppv_event_id>")
def get_ppv_event(ppv_event_id):
    auth(READ_CHECKS)
    p = db.ppv_events.get(ppv_event_id)
    if p is None:
        raise errors.not_found()
    return success(serialize(p))


@bp.get("/api/venues/<venue_id>/ppv-events")
def list_venue_ppv_events(venue_id):
    auth(READ_CHECKS)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([p for p in db.ppv_events.values() if p["venue_id"] == venue_id],
                   key=lambda p: p["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/ppv-events")
def list_ppv_events():
    auth(READ_CHECKS)
    items = sorted(db.ppv_events.values(), key=lambda p: p["created_at"])
    venue_id = request.args.get("venue_id")
    event_id = request.args.get("event_id")
    if venue_id is not None:
        items = [p for p in items if p["venue_id"] == venue_id]
    if event_id is not None:
        items = [p for p in items if p["event_id"] == event_id]
    return list_response(serialize_list(items))


# ---------------------------------------------------------------- promo rules

@bp.post("/api/promo-rules")
def create_promo_rule():
    auth(["VenueManager"])
    data = body()
    day_of_week = req_int(data, "day_of_week")
    if day_of_week < 0 or day_of_week > 6:
        raise invalid_request("day_of_week must be between 0 and 6")
    wing_kind = require(data, "wing_kind")
    if wing_kind not in ("TRADITIONAL", "BONELESS"):
        raise invalid_request("wing_kind must be TRADITIONAL or BONELESS")
    price = req_int(data, "promo_price_cents_per_10", minimum=0)
    start_date = parse_dt(require(data, "start_date"), "start_date")
    end_date = parse_dt(require(data, "end_date"), "end_date")
    if end_date < start_date:
        raise errors.promo_window_invalid("end_date must be on or after start_date")
    # Overlap rejection for same kind/day
    for rule in db.promo_rules.values():
        if rule["wing_kind"] == wing_kind and rule["day_of_week"] == day_of_week:
            if start_date.date() <= rule["end_date"].date() and \
                    rule["start_date"].date() <= end_date.date():
                raise errors.promo_window_invalid(
                    "Overlapping rule for same kind and day_of_week")
    ts = now_ts()
    rule = {
        "id": services.new_id(), "day_of_week": day_of_week,
        "wing_kind": wing_kind, "promo_price_cents_per_10": price,
        "portion_size": 10, "start_date": start_date, "end_date": end_date,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.promo_rules[rule["id"]] = rule
    return success(serialize(rule), code=201)


@bp.get("/api/promo-rules/<promo_rule_id>")
def get_promo_rule(promo_rule_id):
    auth(READ_PROMOS)
    r = db.promo_rules.get(promo_rule_id)
    if r is None:
        raise errors.not_found()
    return success(serialize(r))


@bp.get("/api/promo-rules")
def list_promo_rules():
    auth(READ_PROMOS)
    items = sorted(db.promo_rules.values(), key=lambda r: r["created_at"])
    dow = request.args.get("day_of_week")
    wing_kind = request.args.get("wing_kind")
    if dow is not None:
        try:
            dow_int = int(dow)
        except ValueError:
            raise invalid_request("day_of_week must be an integer")
        items = [r for r in items if r["day_of_week"] == dow_int]
    if wing_kind is not None:
        items = [r for r in items if r["wing_kind"] == wing_kind]
    return list_response(serialize_list(items))
