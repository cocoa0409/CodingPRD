"""Community-signal routes (PRD §4, §3.12)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import fuel as svc

bp = Blueprint("signals", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/community-signals")
def raise_signal():
    identity, role = mw.authenticate(("Member", "PodOperator"))
    data = mw.body()
    row = svc.raise_signal(data, mw, identity, role)
    return created(svc.serialize(row))


@bp.get("/car-share/community-signals")
def list_signals():
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_signals(mw.query("pod_id"), mw.query("signal_type"),
                                  mw.query("member_id"), mw.query("reservation_id"),
                                  limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/community-signals/<signal_id>")
def get_signal(signal_id):
    mw.authenticate(("Member", "PodOperator", "FleetAdmin"))
    row = svc.get_signal(signal_id)
    return ok(svc.serialize(row))