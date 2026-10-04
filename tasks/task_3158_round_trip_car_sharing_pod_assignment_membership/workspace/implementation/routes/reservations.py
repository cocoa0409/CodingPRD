"""Reservation routes (PRD §4, §3.6, §3.8, §3.10, §3.11)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import reservations as svc

bp = Blueprint("reservations", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/reservations")
def create_reservation():
    identity, role = mw.authenticate(("Member",))
    data = mw.body()
    row = svc.create(data, mw, identity, role)
    return created(svc.serialize(row))


@bp.get("/car-share/reservations")
def list_reservations():
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_reservations(mw.query("member_id"), mw.query("pod_id"),
                                       mw.query("vehicle_id"), mw.query("returned_pod_id"),
                                       mw.query("status"), mw.query("start_at"),
                                       limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/reservations/<reservation_id>")
def get_reservation(reservation_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    row = svc.get(reservation_id)
    mw.require_owner(identity, role, row["member_id"])
    return ok(svc.serialize(row))


@bp.post("/car-share/reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    identity, role = mw.authenticate(("Member", "PodOperator"))
    data = mw.body()
    row = svc.cancel(reservation_id, data, mw, identity, role)
    return ok(svc.serialize(row))


@bp.post("/car-share/reservations/<reservation_id>/return")
def return_vehicle(reservation_id):
    identity, role = mw.authenticate(("Member",))
    data = mw.body()
    row = svc.return_vehicle(reservation_id, data, mw, identity, role)
    return ok(svc.serialize(row))


@bp.post("/car-share/reservations/<reservation_id>/close")
def close_reservation(reservation_id):
    identity, role = mw.authenticate(("Member", "PodOperator"))
    row = svc.close(reservation_id, identity, role)
    return ok(svc.serialize(row))


@bp.post("/car-share/reservations/<reservation_id>/reopen-overdue")
def reopen_overdue(reservation_id):
    mw.authenticate(("PodOperator",))
    row = svc.reopen_overdue(reservation_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/reservations/<reservation_id>/resolve-overdue")
def resolve_overdue(reservation_id):
    mw.authenticate(("PodOperator",))
    row = svc.resolve_overdue(reservation_id)
    return ok(svc.serialize(row))


@bp.get("/car-share/reservations/<reservation_id>/access-events")
def reservation_access_events(reservation_id):
    mw.authenticate(("Member", "PodOperator"))
    from services import access as a_svc
    rows = svc.access_events_for_reservation(reservation_id)
    return ok([a_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})