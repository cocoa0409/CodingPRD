"""Replay asset routes, property-economics report, and logical clock."""
from flask import Blueprint, request

import clock
import sweep
import util
from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import replay as svc
from util import get_or_404, get_body

bp = Blueprint("misc", __name__)

READ = ["RightsManager", "StreamOps", "Viewer"]


@bp.get("/platform/replay-assets")
def list_assets():
    require_roles(READ)
    items = by_created(list(db.replay_assets.values()))
    for f in ("window_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(a) for a in page], limit, offset, total)


@bp.get("/platform/replay-assets/<aid>")
def get_asset(aid):
    require_roles(READ)
    return ok_obj(ser(get_or_404("replay_assets", aid)))


@bp.post("/platform/replay-assets/<aid>/pull")
def pull(aid):
    require_roles(["RightsManager"])
    asset = get_or_404("replay_assets", aid)
    svc.pull_asset(asset)
    return ok_obj(ser(asset))


@bp.get("/platform/reports/property-economics")
def report():
    require_roles(["RightsManager"])
    pid = request.args.get("property_id")
    if not pid:
        from errors import raise_err, ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "property_id query parameter required")
    return ok_obj(svc.property_economics(pid))


@bp.post("/platform/_clock/set_current_utc")
def set_clock():
    require_roles(["StreamOps"])
    body = get_body()
    util.require_fields(body, ["to_iso8601"])
    dt = util.req_dt(body["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    sweep.sweep_all()
    return ok_obj({"current_utc": clock.now_iso()})
