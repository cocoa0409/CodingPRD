"""Pod routes (PRD §4, §3.5)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import fleet as svc

bp = Blueprint("pods", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.get("/car-share/pods")
def list_pods():
    mw.authenticate(("Member", "PodOperator", "FleetAdmin", "Anonymous"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_pods(mw.query("site_type"), limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.post("/car-share/pods")
def create_pod():
    mw.authenticate(("FleetAdmin",))
    data = mw.body()
    row = svc.create_pod(data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/pods/<pod_id>")
def get_pod(pod_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin", "Anonymous"))
    row = svc.get_pod(pod_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/pods/<pod_id>/reclassify")
def reclassify(pod_id):
    mw.authenticate(("FleetAdmin",))
    data = mw.body()
    row = svc.reclassify_pod(pod_id, data, mw)
    return ok(svc.serialize(row))


@bp.get("/car-share/pods/<pod_id>/vehicles")
def pod_vehicles(pod_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin", "Anonymous"))
    rows = svc.pod_vehicles(pod_id)
    return ok([svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/pods/<pod_id>/community-signals")
def pod_signals(pod_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    from services import fuel as f_svc
    rows = f_svc.signals_for_pod(pod_id)
    return ok([f_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/pods/<pod_id>/reservations")
def pod_reservations(pod_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    from services import reservations as r_svc
    rows = r_svc.reservations_for_pod(pod_id)
    return ok([r_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/pods/<pod_id>/maintenance-orders")
def pod_maintenance(pod_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    from services import maintenance as mo_svc
    rows = mo_svc.orders_for_pod(pod_id)
    return ok([mo_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/pods/<pod_id>/access-events")
def pod_access_events(pod_id):
    mw.authenticate(("Member", "PodOperator"))
    from services import access as a_svc
    rows = a_svc.access_events_for_pod(pod_id)
    return ok([a_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.get("/car-share/pods/<pod_id>/shift-bundles")
def pod_bundles(pod_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    rows = svc.bundles_for_pod(pod_id)
    return ok([svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})