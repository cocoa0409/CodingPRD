"""Maintenance-order routes (PRD §4, §3.12)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import maintenance as svc

bp = Blueprint("maintenance", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/maintenance-orders")
def create_order():
    mw.authenticate(("PodOperator",))
    data = mw.body()
    vehicle_id = mw.field(data, "vehicle_id", "string", required=True)
    row = svc.create_for_vehicle(vehicle_id, data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/maintenance-orders")
def list_orders():
    mw.authenticate(("PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_orders(mw.query("vehicle_id"), mw.query("pod_id"),
                                 mw.query("incident_id"), mw.query("status"),
                                 limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/maintenance-orders/<order_id>")
def get_order(order_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    row = svc.get(order_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/maintenance-orders/<order_id>/start")
def start_order(order_id):
    mw.authenticate(("PodOperator",))
    row = svc.start(order_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/maintenance-orders/<order_id>/complete")
def complete_order(order_id):
    mw.authenticate(("PodOperator",))
    row = svc.complete(order_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/maintenance-orders/<order_id>/cancel")
def cancel_order(order_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    row = svc.cancel(order_id, data, mw)
    return ok(svc.serialize(row))