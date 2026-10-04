"""Disruption events: declare, list, get."""

from flask import Blueprint, request

import db
from common import new_entity, get_or_404, body, require_field, require_enum
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate
from routes.routes import _get_route_or_404, _cancel_flight
from routes.flight_instances import _get_flight_or_404

bp = Blueprint("disruptions", __name__)

REASON_CODES = {"WEATHER", "MAINTENANCE", "CREW_SHORTAGE", "LOW_DEMAND"}


def _get_disruption_or_404(dis_id):
    return get_or_404(
        db.disruption_events, dis_id, "ERR_DISRUPTION_NOT_FOUND", "DisruptionEvent"
    )


@bp.route("/routes/<route_id>/disruptions", methods=["POST"])
def declare_disruption(route_id):
    require_role("OpsController")
    route = _get_route_or_404(route_id)
    data = body()
    flight_id = require_field(data, "flight_instance_id", str)
    flight = db.flight_instances.get(flight_id)
    if flight is None:
        raise ApiError(
            "ERR_FLIGHT_NOT_FOUND", "FlightInstance id does not exist", 404
        )
    reason = require_enum(data, "reason_code", REASON_CODES)
    if flight["route_id"] != route_id:
        raise ApiError(
            "ERR_FLIGHT_NOT_FOUND", "FlightInstance id does not exist", 404
        )
    if flight["flight_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_FLIGHT_NOT_SCHEDULED",
            "Operation requires SCHEDULED flight",
            409,
        )
    dis = new_entity(
        {
            "route_id": route_id,
            "flight_instance_id": flight_id,
            "reason_code": reason,
            "disruption_status": "DECLARED",
        }
    )
    db.disruption_events[dis["id"]] = dis
    _cancel_flight(flight, dis)
    return ok(dis, 201)


@bp.route("/routes/<route_id>/disruptions", methods=["GET"])
def list_disruptions_for_route(route_id):
    require_any_authenticated()
    _get_route_or_404(route_id)
    items = [d for d in db.disruption_events.values() if d["route_id"] == route_id]
    status = request.args.get("disruption_status")
    if status:
        items = [d for d in items if d["disruption_status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/disruptions", methods=["GET"])
def list_disruptions_flat():
    require_any_authenticated()
    items = list(db.disruption_events.values())
    rid = request.args.get("route_id")
    if rid:
        items = [d for d in items if d["route_id"] == rid]
    fid = request.args.get("flight_instance_id")
    if fid:
        items = [d for d in items if d["flight_instance_id"] == fid]
    status = request.args.get("disruption_status")
    if status:
        items = [d for d in items if d["disruption_status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/disruptions/<dis_id>", methods=["GET"])
def get_disruption(dis_id):
    require_any_authenticated()
    ent = _get_disruption_or_404(dis_id)
    return ok(ent)
