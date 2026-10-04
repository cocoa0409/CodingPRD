"""Venue, RiggingPoint, DateAvail endpoints."""
from flask import Blueprint, request

from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
from constants import ALL_ROLES, UNION_RULE_SETS
import helpers as H
import ticks

bp = Blueprint("venues", __name__)


@bp.route("/venues", methods=["POST"])
@require_roles("VenueBooker", "PlatformAdmin")
def create_venue():
    data = H.body()
    H.require_fields(data, ["name", "market_code", "capacity_seats", "load_in_dock_doors",
                            "union_rule_set", "default_rent_cents", "percentage_share_pct"])
    v = base_fields()
    v.update({
        "name": H.req_str(data, "name"),
        "market_code": H.req_str(data, "market_code"),
        "capacity_seats": H.req_int(data, "capacity_seats"),
        "load_in_dock_doors": H.req_int(data, "load_in_dock_doors"),
        "union_rule_set": H.req_enum(data, "union_rule_set", UNION_RULE_SETS),
        "default_rent_cents": H.req_int(data, "default_rent_cents"),
        "percentage_share_pct": H.opt_num(data, "percentage_share_pct", 0.0),
        "standard_load_in_hours": H.opt_int(data, "standard_load_in_hours", 8),
        "status": "ACTIVE",
    })
    if not (0.0 <= float(v["percentage_share_pct"]) <= 0.5):
        raise err("ERR_INVALID_REQUEST", "percentage_share_pct must be in 0.0..0.5")
    db.venues[v["id"]] = v
    return success(v, 201)


@bp.route("/venues", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_venues():
    items = list(db.venues.values())
    status = request.args.get("status")
    market = request.args.get("market_code")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    if market is not None:
        items = [v for v in items if v["market_code"] == market]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/venues/<venueId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_venue(venueId):
    return success(H.get_venue(venueId))


@bp.route("/venues/<venueId>/deactivate", methods=["POST"])
@require_roles("PlatformAdmin")
def deactivate_venue(venueId):
    v = H.get_venue(venueId)
    for e in db.engagements.values():
        if e["venue_id"] == v["id"] and e["status"] in H.OPEN_ENGAGEMENT_STATUSES:
            raise err("ERR_VENUE_HAS_OPEN_ENGAGEMENTS",
                      "Venue has open engagement %s" % e["id"])
    v["status"] = "INACTIVE"
    touch(v)
    for a in db.date_avails.values():
        if a["venue_id"] == v["id"] and a["status"] == "OPEN":
            a["status"] = "RELEASED"
            touch(a)
    return success(v)


# ---------- RiggingPoint ----------

@bp.route("/venues/<venueId>/rigging-points", methods=["POST"])
@require_roles("VenueBooker", "PlatformAdmin")
def create_point(venueId):
    v = H.get_venue(venueId)
    data = H.body()
    H.require_fields(data, ["label", "zone", "max_static_load_kg", "max_dynamic_load_kg"])
    p = base_fields()
    p.update({
        "venue_id": v["id"],
        "label": H.req_str(data, "label"),
        "zone": H.req_str(data, "zone"),
        "max_static_load_kg": H.req_int(data, "max_static_load_kg"),
        "max_dynamic_load_kg": H.req_int(data, "max_dynamic_load_kg"),
        "engineering_review_required": H.opt_bool(data, "engineering_review_required", True),
        "status": "AVAILABLE",
    })
    db.rigging_points[p["id"]] = p
    return success(p, 201)


@bp.route("/venues/<venueId>/rigging-points", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_points(venueId):
    H.get_venue(venueId)
    items = [p for p in db.rigging_points.values() if p["venue_id"] == venueId]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/venues/<venueId>/rigging-points/<pointId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_point(venueId, pointId):
    H.get_venue(venueId)
    return success(H.get_point(venueId, pointId))


@bp.route("/venues/<venueId>/rigging-points/<pointId>/mark-out-of-service", methods=["POST"])
@require_roles("PlatformAdmin", "ProductionEngineer")
def mark_point_oos(venueId, pointId):
    H.get_venue(venueId)
    p = H.get_point(venueId, pointId)
    p["status"] = "OUT_OF_SERVICE"
    touch(p)
    return success(p)


# ---------- DateAvail ----------

@bp.route("/venues/<venueId>/date-avails", methods=["POST"])
@require_roles("VenueBooker")
def create_avail(venueId):
    v = H.get_venue(venueId)
    data = H.body()
    H.require_fields(data, ["opens_at", "closes_at"])
    opens = H.req_dt(data, "opens_at")
    closes = H.req_dt(data, "closes_at")
    if opens >= closes:
        raise err("ERR_INVALID_AVAIL_WINDOW", "opens_at must be strictly before closes_at")
    for a in db.date_avails.values():
        if a["venue_id"] != v["id"] or a["status"] == "RELEASED":
            continue
        # half-open overlap; adjacency allowed
        if opens < a["closes_at"] and closes > a["opens_at"]:
            raise err("ERR_AVAIL_OVERLAP", "DateAvail overlaps existing avail %s" % a["id"])
    a = base_fields()
    a.update({
        "venue_id": v["id"],
        "opens_at": opens,
        "closes_at": closes,
        "priority_rank": H.opt_int(data, "priority_rank", 100),
        "status": "OPEN",
        "held_for_engagement_id": None,
    })
    db.date_avails[a["id"]] = a
    return success(a, 201)


@bp.route("/venues/<venueId>/date-avails", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_avails(venueId):
    H.get_venue(venueId)
    items = [a for a in db.date_avails.values() if a["venue_id"] == venueId]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/venues/<venueId>/date-avails/<availId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_avail(venueId, availId):
    H.get_venue(venueId)
    return success(H.get_avail(venueId, availId))


@bp.route("/venues/<venueId>/date-avails/<availId>/release", methods=["POST"])
@require_roles("VenueBooker")
def release_avail(venueId, availId):
    H.get_venue(venueId)
    a = H.get_avail(venueId, availId)
    if a["status"] == "OPEN":
        a["status"] = "RELEASED"
        touch(a)
        return success(a)
    if a["status"] == "HELD":
        eng = db.engagements.get(a.get("held_for_engagement_id") or "")
        if eng is not None and eng["status"] == "HOLD":
            ticks.cancel_engagement(eng, reason="AVAIL_FORCE_RELEASED", from_status="HOLD")
            a["status"] = "RELEASED"
            a["held_for_engagement_id"] = None
            touch(a)
            return success(a)
        raise err("ERR_AVAIL_NOT_OPEN",
                  "Held avail can only be force-released while engagement is in HOLD")
    raise err("ERR_AVAIL_NOT_OPEN", "Avail must be OPEN to release")
