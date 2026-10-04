"""Viewer and view-grant routes."""
from flask import Blueprint, request

from db import db
from errors import raise_err, ERR_FORBIDDEN
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import viewer as svc
from util import get_or_404, get_body

bp = Blueprint("viewers", __name__)


@bp.post("/platform/viewers")
def create():
    require_roles(["Viewer"])
    viewer = svc.create_viewer(get_body())
    return ok_obj(ser(viewer), 201)


@bp.get("/platform/viewers")
def list_all():
    require_roles(["PartnerManager"])
    items = by_created(list(db.viewers.values()))
    awid = request.args.get("acquisition_window_id")
    if awid is not None:
        items = [v for v in items if v.get("acquisition_window_id") == awid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(v) for v in page], limit, offset, total)


@bp.get("/platform/viewers/<vid>")
def get_one(vid):
    user_id, role = require_roles(["PartnerManager", "Viewer"])
    viewer = get_or_404("viewers", vid)
    if role == "Viewer" and vid != user_id:
        raise_err(ERR_FORBIDDEN, "viewer may only read own record")
    return ok_obj(ser(viewer))


@bp.post("/platform/viewers/<vid>/reactivate")
def reactivate(vid):
    require_roles(["PartnerManager"])
    viewer = get_or_404("viewers", vid)
    svc.reactivate(viewer)
    return ok_obj(ser(viewer))


@bp.post("/platform/viewers/<vid>/suspend-billing")
def suspend_billing(vid):
    require_roles(["PartnerManager"])
    viewer = get_or_404("viewers", vid)
    svc.suspend_billing(viewer)
    return ok_obj(ser(viewer))


@bp.post("/platform/viewers/<vid>/cancel")
def cancel(vid):
    user_id, _ = require_roles(["Viewer"])
    viewer = get_or_404("viewers", vid)
    if vid != user_id:
        raise_err(ERR_FORBIDDEN, "viewer may only cancel own subscription")
    svc.cancel(viewer)
    return ok_obj(ser(viewer))


@bp.get("/platform/view-grants")
def list_grants():
    user_id, role = require_roles(["StreamOps", "Viewer", "RightsManager"])
    items = by_created(list(db.view_grants.values()))
    for f in ("viewer_id", "window_id"):
        v = request.args.get(f)
        if v is not None:
            items = [g for g in items if g.get(f) == v]
    if role == "Viewer":
        items = [g for g in items if g["viewer_id"] == user_id]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(g) for g in page], limit, offset, total)


@bp.get("/platform/view-grants/<gid>")
def get_grant(gid):
    user_id, role = require_roles(["StreamOps", "Viewer", "RightsManager"])
    grant = get_or_404("view_grants", gid)
    if role == "Viewer" and grant["viewer_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "viewer may only read own grants")
    return ok_obj(ser(grant))
