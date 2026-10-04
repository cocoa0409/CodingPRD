"""Incident routes (PRD §4, §3.13)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import incidents as svc
from services import maintenance as mo_svc

bp = Blueprint("incidents", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/incidents")
def create_incident():
    identity, role = mw.authenticate(("Member", "PodOperator"))
    data = mw.body()
    row = svc.create(data, mw, identity, role)
    return created(svc.serialize(row))


@bp.get("/car-share/incidents")
def list_incidents():
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_incidents(mw.query("reservation_id"), mw.query("vehicle_id"),
                                    mw.query("member_id"),
                                    mw.query("assigned_driver_member_id"),
                                    mw.query("status"), limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/incidents/<incident_id>")
def get_incident(incident_id):
    identity, role = mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    row = svc.get(incident_id)
    mw.require_owner(identity, role, row["member_id"])
    return ok(svc.serialize(row))


@bp.get("/car-share/incidents/<incident_id>/party-split")
def get_party_split(incident_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    row = svc.get(incident_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/incidents/<incident_id>/party-split")
def party_split(incident_id):
    identity, role = mw.authenticate(("PodOperator",))
    data = mw.body()
    row = svc.party_split(incident_id, data, mw, identity, role)
    return ok(svc.serialize(row))


@bp.post("/car-share/incidents/<incident_id>/maintenance-orders")
def incident_maintenance_orders(incident_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    row = mo_svc.create_for_incident(incident_id, data, mw)
    return created(mo_svc.serialize(row))


@bp.get("/car-share/incidents/<incident_id>/maintenance-orders")
def list_incident_maintenance_orders(incident_id):
    mw.authenticate(("PodOperator", "FleetAdmin"))
    rows = mo_svc.orders_for_incident(incident_id)
    return ok([mo_svc.serialize(r) for r in rows], response_type="array",
              pagination={"limit": 10, "offset": 0, "total_count": len(rows),
                          "has_more": False})


@bp.post("/car-share/incidents/<incident_id>/waive-fee")
def waive_fee(incident_id):
    mw.authenticate(("PodOperator",))
    data = mw.body()
    row = svc.waive_fee(incident_id, data, mw)
    return ok(svc.serialize(row))