"""Engagement endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from clock import now, to_iso
from constants import ALL_ROLES, DEAL_TYPES, HOLD_TTL_HOURS
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import calc
import helpers as H
import ticks

bp = Blueprint("engagements", __name__)


def engagement_view(e):
    ticks.tick_engagement(e)
    out = dict(e)
    out.pop("_cancel_from", None)
    for f in ("load_in_at", "first_show_at", "load_out_at", "hold_expires_at"):
        if f in out and out[f] is not None and not isinstance(out[f], str):
            out[f] = to_iso(out[f])
    tour = db.tours.get(e["tour_id"])
    if tour is not None and e["status"] in ("HOLD", "CONFIRMED"):
        out["market_overlap_flag"] = calc.market_overlap(e, tour)
    return out


@bp.route("/tours/<tourId>/engagements", methods=["POST"])
@require_roles("TourManager")
def create_engagement(tourId):
    t = H.get_tour(tourId)
    data = H.body()
    # body FK existence (priority 4)
    venue_id = data.get("venue_id")
    avail_id = data.get("date_avail_id")
    if venue_id is not None:
        H.get_venue(venue_id)
    if avail_id is not None and venue_id is not None:
        H.get_avail(venue_id, avail_id)
    H.require_fields(data, ["venue_id", "date_avail_id", "load_in_at", "first_show_at",
                            "load_out_at", "deal_type", "agreed_rent_cents",
                            "expected_avail_version"])
    venue = H.get_venue(venue_id)
    avail = H.get_avail(venue_id, avail_id)
    deal_type = H.req_enum(data, "deal_type", DEAL_TYPES)
    agreed_rent = H.req_int(data, "agreed_rent_cents")
    load_in = H.req_dt(data, "load_in_at")
    first_show = H.req_dt(data, "first_show_at")
    load_out = H.req_dt(data, "load_out_at")
    # temporal: internal consistency (400) then containment (422)
    if not (load_in < first_show < load_out):
        raise err("ERR_INVALID_ENGAGEMENT_TIMES",
                  "load_in_at < first_show_at < load_out_at required")
    if load_in < avail["opens_at"] or load_out >= avail["closes_at"]:
        raise err("ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL",
                  "Engagement must fit half-open inside the avail window")
    # avail must be OPEN (state)
    if avail["status"] != "OPEN":
        raise err("ERR_AVAIL_NOT_OPEN", "DateAvail is not OPEN")
    # OCC
    expected = data.get("expected_avail_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_avail_version must be an integer")
    if expected != avail["version"]:
        raise err("ERR_STALE_AVAIL_VERSION",
                  "expected_avail_version %s != current %s" % (expected, avail["version"]))
    e = base_fields()
    e.update({
        "tour_id": t["id"],
        "venue_id": venue["id"],
        "date_avail_id": avail["id"],
        "load_in_at": load_in,
        "first_show_at": first_show,
        "load_out_at": load_out,
        "deal_type": deal_type,
        "agreed_rent_cents": agreed_rent,
        "status": "HOLD",
        "hold_expires_at": now() + timedelta(hours=HOLD_TTL_HOURS),
        "market_overlap_flag": calc.market_overlap({"id": None, "tour_id": t["id"],
                                                    "venue_id": venue["id"],
                                                    "first_show_at": first_show}, t),
    })
    db.engagements[e["id"]] = e
    avail["status"] = "HELD"
    avail["held_for_engagement_id"] = e["id"]
    touch(avail)
    ticks.recompute_tour_counters(t)
    return success(engagement_view(e), 201)


@bp.route("/tours/<tourId>/engagements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_engagements(tourId):
    H.get_tour(tourId)
    items = [e for e in db.engagements.values() if e["tour_id"] == tourId]
    for e in items:
        ticks.tick_engagement(e)
    status = request.args.get("status")
    venue_id = request.args.get("venue_id")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if venue_id is not None:
        items = [e for e in items if e["venue_id"] == venue_id]
    items = [engagement_view(e) for e in items]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_engagement(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    return success(engagement_view(e))


@bp.route("/tours/<tourId>/engagements/<engagementId>/confirm", methods=["POST"])
@require_roles("TourManager")
def confirm_engagement(tourId, engagementId):
    t = H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    if e["status"] != "HOLD":
        raise err("ERR_ENGAGEMENT_NOT_IN_HOLD", "Engagement must be in HOLD to confirm")
    if now() >= e["hold_expires_at"]:
        raise err("ERR_HOLD_EXPIRED", "Hold has expired")
    if calc.market_overlap(e, t):
        e["market_overlap_flag"] = True
        raise err("ERR_MARKET_COOLDOWN_VIOLATION", "Market cooldown violated")
    venue = db.venues.get(e["venue_id"])
    if venue is None or venue["status"] != "ACTIVE":
        raise err("ERR_VENUE_INACTIVE", "Venue is not ACTIVE")
    e["status"] = "CONFIRMED"
    e["market_overlap_flag"] = False
    touch(e)
    avail = db.date_avails.get(e["date_avail_id"])
    if avail is not None and avail["status"] == "HELD":
        avail["status"] = "BOOKED"
        touch(avail)
    ticks.tick_tour(t)
    return success(engagement_view(e))


@bp.route("/tours/<tourId>/engagements/<engagementId>/cancel", methods=["POST"])
@require_roles("TourManager")
def cancel_engagement(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    if e["status"] == "HOLD":
        ticks.cancel_engagement(e, from_status="HOLD")
        return success(engagement_view(e))
    if e["status"] == "CONFIRMED":
        if now() >= e["load_in_at"]:
            raise err("ERR_TOO_LATE_TO_CANCEL", "Cannot cancel at or after load_in_at")
        ticks.cancel_engagement(e, from_status="CONFIRMED")
        return success(engagement_view(e))
    raise err("ERR_INVALID_STATE", "Engagement in %s cannot be cancelled" % e["status"])


@bp.route("/tours/<tourId>/engagements/<engagementId>/mark-show-ready", methods=["POST"])
@require_roles("ProductionEngineer")
def mark_show_ready(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    if e["status"] != "IN_LOAD":
        raise err("ERR_INVALID_STATE", "Engagement must be IN_LOAD to mark show-ready")
    approved = [p for p in db.rigging_plans.values()
                if p["engagement_id"] == e["id"] and p["status"] == "APPROVED"]
    if not approved:
        raise err("ERR_RIGGING_NOT_APPROVED", "No APPROVED rigging plan exists")
    for i in db.safety_inspections.values():
        if i["engagement_id"] == e["id"] and i["status"] not in ("PASSED", "WAIVED"):
            raise err("ERR_INSPECTION_OUTSTANDING",
                      "Inspection %s is %s" % (i["id"], i["status"]))
    e["status"] = "SHOW_READY"
    touch(e)
    ticks.tick_engagement(e)
    return success(engagement_view(e))
