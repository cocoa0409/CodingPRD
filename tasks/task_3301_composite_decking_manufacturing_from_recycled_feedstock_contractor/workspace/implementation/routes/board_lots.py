"""Board lots: get + list with filters."""
from flask import Blueprint, request

import db as dbmod
from middleware import require_roles
from services.lookup import get_path
from util import ok_object, ok_list

bp = Blueprint("board_lots", __name__)


@bp.get("/decking/board-lots/<lid>")
@require_roles("OpsManager", "QualityEngineer", "ClaimsAdjuster")
def get_lot(lid):
    return ok_object(dict(get_path("board_lots", lid)))


@bp.get("/decking/board-lots")
@require_roles("OpsManager", "ClaimsAdjuster")
def list_lots():
    items = list(dbmod.db.board_lots.values())
    for f in ("product_line_id", "disposition", "production_run_id"):
        v = request.args.get(f)
        if v:
            items = [l for l in items if str(l.get(f)) == v]
    v = request.args.get("support_tagged")
    if v is not None:
        want = v.lower() == "true"
        items = [l for l in items if bool(l.get("support_tagged")) == want]
    return ok_list([dict(l) for l in items])


@bp.get("/decking/plants/<pid>/board-lots")
@require_roles("OpsManager", "QualityEngineer", "ClaimsAdjuster")
def plant_lots(pid):
    get_path("plants", pid)
    items = [l for l in dbmod.db.board_lots.values() if l["plant_id"] == pid]
    v = request.args.get("disposition")
    if v:
        items = [l for l in items if l["disposition"] == v]
    v = request.args.get("support_tagged")
    if v is not None:
        want = v.lower() == "true"
        items = [l for l in items if bool(l.get("support_tagged")) == want]
    return ok_list([dict(l) for l in items])
