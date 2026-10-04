"""Tour endpoints."""
from flask import Blueprint, request

from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
from constants import ALL_ROLES
import helpers as H
import ticks

bp = Blueprint("tours", __name__)


def tour_view(t):
    ticks.tick_tour(t)
    return t


@bp.route("/tours", methods=["POST"])
@require_roles("TourManager")
def create_tour():
    data = H.body()
    H.require_fields(data, ["name", "home_base_city", "season_start_on", "season_end_on"])
    name = H.req_str(data, "name")
    home_base_city = H.req_str(data, "home_base_city")
    season_start_on = H.req_dt(data, "season_start_on")
    season_end_on = H.req_dt(data, "season_end_on")
    cooldown = H.opt_int(data, "market_cooldown_days", 180)
    reserve = H.opt_num(data, "royalty_reserve_pct", 0.0)
    t = base_fields()
    t.update({
        "name": name,
        "home_base_city": home_base_city,
        "season_start_on": season_start_on,
        "season_end_on": season_end_on,
        "market_cooldown_days": cooldown,
        "royalty_reserve_pct": reserve,
        "status": "PLANNING",
        "total_gross_cents": 0,
        "total_settlement_due_cents": 0,
        "open_engagement_count": 0,
    })
    db.tours[t["id"]] = t
    return success(t, 201)


@bp.route("/tours", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_tours():
    ticks.tick_all()
    items = list(db.tours.values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_tour(tourId):
    t = H.get_tour(tourId)
    ticks.tick_tour(t)
    return success(tour_view(t))


@bp.route("/tours/<tourId>/open-routing", methods=["POST"])
@require_roles("TourManager")
def open_routing(tourId):
    t = H.get_tour(tourId)
    if t["status"] != "PLANNING":
        raise err("ERR_TOUR_NOT_IN_PLANNING", "Tour must be in PLANNING to open routing")
    t["status"] = "ROUTING"
    touch(t)
    return success(t)


@bp.route("/tours/<tourId>/close", methods=["POST"])
@require_roles("TourManager")
def close_tour(tourId):
    t = H.get_tour(tourId)
    ticks.tick_tour(t)
    if t["status"] != "WRAP":
        raise err("ERR_TOUR_NOT_READY_TO_CLOSE", "Tour must be in WRAP to close")
    for e in db.engagements.values():
        if e["tour_id"] != t["id"]:
            continue
        sid = db.settlements_by_eng.get(e["id"])
        if sid is None:
            if e["status"] not in ("CANCELLED",):
                raise err("ERR_TOUR_NOT_READY_TO_CLOSE",
                          "Engagement %s has no settlement" % e["id"])
            continue
        s = db.settlements[sid]
        if s["status"] not in ("RECONCILED", "PAID"):
            raise err("ERR_TOUR_NOT_READY_TO_CLOSE",
                      "Settlement %s not reconciled/paid" % s["id"])
    for l in db.license_agreements.values():
        if l["tour_id"] != t["id"]:
            continue
        ticks.tick_license(l)
        if l["status"] not in ("ACTIVE", "EXPIRED", "TERMINATED"):
            raise err("ERR_TOUR_NOT_READY_TO_CLOSE",
                      "LicenseAgreement %s not terminal/active" % l["id"])
    t["status"] = "CLOSED"
    touch(t)
    return success(t)
