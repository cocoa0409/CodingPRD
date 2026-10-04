"""Window routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import paginate, by_created
from services import window as svc
from services import viewer as viewer_svc
from services.adslot import pod_summary
from util import get_or_404, get_body
from serialize import serialize as ser

bp = Blueprint("windows", __name__)

ALL_READ = ["RightsManager", "AdOps", "StreamOps", "PartnerManager", "Viewer"]


@bp.post("/platform/windows")
def create():
    require_roles(["RightsManager"])
    win = svc.create_window(get_body())
    return ok_obj(ser(win), 201)


@bp.get("/platform/windows")
def list_all():
    require_roles(ALL_READ)
    items = by_created(list(db.windows.values()))
    for f in ("property_id", "status", "rights_mode", "replaced_by_id", "supersedes_id"):
        v = request.args.get(f)
        if v is not None:
            items = [w for w in items if str(w.get(f)) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(w) for w in page], limit, offset, total)


@bp.get("/platform/windows/<wid>")
def get_one(wid):
    require_roles(ALL_READ)
    return ok_obj(ser(get_or_404("windows", wid)))


@bp.post("/platform/windows/<wid>/go-live")
def go_live(wid):
    require_roles(["RightsManager"])
    win = get_or_404("windows", wid)
    svc.go_live(win)
    return ok_obj(ser(win))


@bp.post("/platform/windows/<wid>/complete")
def complete(wid):
    require_roles(["RightsManager"])
    win = get_or_404("windows", wid)
    svc.complete_window(win)
    return ok_obj(ser(win))


@bp.post("/platform/windows/<wid>/cancel")
def cancel(wid):
    require_roles(["RightsManager"])
    win = get_or_404("windows", wid)
    svc.cancel_window_endpoint(win)
    return ok_obj(ser(win))


@bp.get("/platform/windows/<wid>/pods")
def pods(wid):
    require_roles(["AdOps", "RightsManager"])
    win = get_or_404("windows", wid)
    summary = pod_summary(win)
    data = {
        "breaks": [
            {
                "break_index": b["break_index"],
                "open_seconds": b["open_seconds"],
                "filled_seconds": b["filled_seconds"],
                "unfillable": b["unfillable"],
                "slots": [ser(s) for s in b["slots"]],
            }
            for b in summary["breaks"]
        ],
        "total_open_seconds": summary["total_open_seconds"],
        "total_filled_seconds": summary["total_filled_seconds"],
    }
    return ok_obj(data)


@bp.post("/platform/windows/<wid>/view-grants")
def view_grants(wid):
    user_id, _ = require_roles(["Viewer"])
    win = get_or_404("windows", wid)
    grant = viewer_svc.issue_view_grant(win, get_body(), user_id)
    return ok_obj(ser(grant), 201)
