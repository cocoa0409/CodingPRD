"""Property routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import paginate, by_created
from services import property as svc
from services.window import serialize as ser_window
from util import get_or_404

bp = Blueprint("properties", __name__)

ALL_READ = ["RightsManager", "AdOps", "StreamOps", "PartnerManager"]


@bp.post("/platform/properties")
def create():
    require_roles(["RightsManager"])
    from flask import request as _r
    prop = svc.create_property(_r.get_json(silent=True) or {})
    return ok_obj(svc.serialize(prop), 201)


@bp.get("/platform/properties")
def list_all():
    require_roles(ALL_READ)
    items = by_created(list(db.properties.values()))
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([svc.serialize(p) for p in page], limit, offset, total)


@bp.get("/platform/properties/<pid>")
def get_one(pid):
    require_roles(ALL_READ + ["Viewer"])
    prop = get_or_404("properties", pid)
    return ok_obj(svc.serialize(prop))


@bp.get("/platform/properties/<pid>/windows")
def list_windows(pid):
    require_roles(ALL_READ)
    get_or_404("properties", pid)
    items = [w for w in by_created(list(db.windows.values())) if w["property_id"] == pid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_window(w) for w in page], limit, offset, total)


@bp.post("/platform/properties/<pid>/activate")
def activate(pid):
    require_roles(["RightsManager"])
    prop = get_or_404("properties", pid)
    svc.activate(prop)
    return ok_obj(svc.serialize(prop))


@bp.post("/platform/properties/<pid>/suspend")
def suspend(pid):
    require_roles(["RightsManager"])
    prop = get_or_404("properties", pid)
    svc.suspend(prop)
    return ok_obj(svc.serialize(prop))


@bp.post("/platform/properties/<pid>/unsuspend")
def unsuspend(pid):
    require_roles(["RightsManager"])
    prop = get_or_404("properties", pid)
    svc.unsuspend(prop)
    return ok_obj(svc.serialize(prop))


@bp.post("/platform/properties/<pid>/terminate")
def terminate(pid):
    require_roles(["RightsManager"])
    prop = get_or_404("properties", pid)
    svc.terminate(prop)
    return ok_obj(svc.serialize(prop))
