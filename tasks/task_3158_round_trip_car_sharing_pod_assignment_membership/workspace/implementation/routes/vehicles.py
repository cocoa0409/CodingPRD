"""Vehicle routes and relocation bundles (PRD §4, §3.5)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import fleet as svc

bp = Blueprint("vehicles", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.get("/car-share/vehicles")
def list_vehicles():
    mw.authenticate(("PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_vehicles(mw.query("pod_id"), mw.query("home_pod_id"),
                                   mw.query("use_status"), mw.query("cleanliness_state"),
                                   limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.post("/car-share/vehicles")
def create_vehicle():
    mw.authenticate(("FleetAdmin",))
    data = mw.body()
    row = svc.create_vehicle(data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin", "Anonymous"))
    row = svc.get_vehicle(vehicle_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/vehicles/<vehicle_id>/availability-events")
def availability_event(vehicle_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    data = mw.body()
    row = svc.availability_event(vehicle_id, data, mw)
    return ok(svc.serialize(row))


@bp.post("/car-share/vehicles/<vehicle_id>/cleanliness-restore")
def cleanliness_restore(vehicle_id):
    mw.authenticate(("PodOperator",))
    row = svc.cleanliness_restore(vehicle_id)
    return ok(svc.serialize(row))


@bp.get("/car-share/vehicles/<vehicle_id>/maintenance-orders")
def vehicle_maintenance(vehicle_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    from services import maintenance as mo_svc
    rows = mo_svc.orders_for_vehicle(vehicle_id)
    return ok([mo_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/vehicles/<vehicle_id>/access-events")
def vehicle_access_events(vehicle_id):
    mw.authenticate(("Member", "PodOperator"))
    from services import access as a_svc
    rows = a_svc.access_events_for_vehicle(vehicle_id)
    return ok([a_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/vehicles/<vehicle_id>/fuel-card-transactions")
def vehicle_fuel(vehicle_id):
    mw.authenticate(("Member", "PodOperator"))
    from services import fuel as f_svc
    rows = f_svc.transactions_for_vehicle(vehicle_id)
    return ok([f_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.post("/car-share/shift-bundles")
def apply_bundle():
    mw.authenticate(("PodOperator",))
    data = mw.body()
    row = svc.apply_shift_bundle(data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/shift-bundles")
def list_bundles():
    mw.authenticate(("PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_shift_bundles(mw.query("source_pod_id"), mw.query("dest_pod_id"),
                                        limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)