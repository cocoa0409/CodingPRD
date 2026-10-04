"""TruckMove endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES, CARGO_KINDS, TRUCK_ARRIVAL_GRACE_HOURS
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import calc
import helpers as H
import ticks

bp = Blueprint("trucks", __name__)


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves", methods=["POST"])
@require_roles("ProductionEngineer")
def create_move(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    data = H.body()
    H.require_fields(data, ["cargo_kind", "truck_count", "arrival_at"])
    m = base_fields()
    m.update({
        "engagement_id": e["id"],
        "cargo_kind": H.req_enum(data, "cargo_kind", CARGO_KINDS),
        "truck_count": H.req_int(data, "truck_count"),
        "arrival_at": H.req_dt(data, "arrival_at"),
        "status": "SCHEDULED",
        "dock_doors_needed": calc.compute_dock_doors(H.req_int(data, "truck_count")),
    })
    db.truck_moves[m["id"]] = m
    return success(m, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_moves(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    items = [m for m in db.truck_moves.values() if m["engagement_id"] == engagementId]
    status = request.args.get("status")
    cargo = request.args.get("cargo_kind")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if cargo is not None:
        items = [m for m in items if m["cargo_kind"] == cargo]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves/<moveId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_move(tourId, engagementId, moveId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_truck_move(engagementId, moveId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves/<moveId>/dispatch", methods=["POST"])
@require_roles("ProductionEngineer")
def dispatch_move(tourId, engagementId, moveId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    m = H.get_truck_move(engagementId, moveId)
    if m["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Move must be SCHEDULED to dispatch")
    if e["status"] not in ("CONFIRMED", "IN_LOAD"):
        raise err("ERR_INVALID_STATE",
                  "Engagement must be CONFIRMED or IN_LOAD to dispatch trucks")
    venue = db.venues[e["venue_id"]]
    if m["dock_doors_needed"] > venue["load_in_dock_doors"]:
        raise err("ERR_DOCK_CAPACITY_EXCEEDED",
                  "dock_doors_needed %s > load_in_dock_doors %s"
                  % (m["dock_doors_needed"], venue["load_in_dock_doors"]))
    m["status"] = "DISPATCHED"
    touch(m)
    return success(m)


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves/<moveId>/mark-arrived", methods=["POST"])
@require_roles("ProductionEngineer")
def arrive_move(tourId, engagementId, moveId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    m = H.get_truck_move(engagementId, moveId)
    if m["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Move must be DISPATCHED to mark arrived")
    if now() < m["arrival_at"] - timedelta(hours=TRUCK_ARRIVAL_GRACE_HOURS):
        raise err("ERR_INVALID_STATE", "Too early to mark arrived")
    m["status"] = "ARRIVED"
    touch(m)
    return success(m)


@bp.route("/tours/<tourId>/engagements/<engagementId>/truck-moves/<moveId>/cancel", methods=["POST"])
@require_roles("ProductionEngineer")
def cancel_move(tourId, engagementId, moveId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    m = H.get_truck_move(engagementId, moveId)
    if m["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Move in %s cannot be cancelled" % m["status"])
    m["status"] = "CANCELLED"
    touch(m)
    return success(m)
