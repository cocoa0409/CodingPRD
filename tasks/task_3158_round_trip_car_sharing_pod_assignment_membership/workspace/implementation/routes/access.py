"""Access-event routes (PRD §4, §3.7)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import access as svc

bp = Blueprint("access", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/access-events")
def create_event():
    identity, role = mw.authenticate(("Member",))
    data = mw.body()
    row = svc.create(data, mw, identity, role)
    return created(svc.serialize(row))


@bp.get("/car-share/access-events")
def list_events():
    mw.authenticate(("Member", "PodOperator"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_access_events(mw.query("reservation_id"), mw.query("member_id"),
                                        mw.query("vehicle_id"), limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/access-events/<event_id>")
def get_event(event_id):
    identity, role = mw.authenticate(("Member", "PodOperator"))
    row = svc.get(event_id)
    mw.require_owner(identity, role, row.get("member_id"))
    return ok(svc.serialize(row))


@bp.post("/car-share/access-events/<event_id>/retry")
def retry_event(event_id):
    mw.authenticate(("PodOperator",))
    row = svc.retry(event_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/access-events/<event_id>/lockout-report")
def lockout_report(event_id):
    identity, role = mw.authenticate(("Member",))
    row = svc.lockout_report(event_id, identity, role)
    return ok(svc.serialize(row))