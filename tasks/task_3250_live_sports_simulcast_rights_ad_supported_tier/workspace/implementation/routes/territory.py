"""Territory rule routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import territory as svc
from util import get_or_404, get_body

bp = Blueprint("territory_rules", __name__)

READ = ["RightsManager", "StreamOps"]


@bp.post("/platform/territory-rules")
def create():
    require_roles(["RightsManager"])
    rule = svc.create_rule(get_body())
    return ok_obj(ser(rule), 201)


@bp.get("/platform/territory-rules")
def list_all():
    require_roles(READ)
    items = by_created(list(db.territory_rules.values()))
    for f in ("window_id", "region_code", "rule_status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(r) for r in page], limit, offset, total)


@bp.get("/platform/territory-rules/<rid>")
def get_one(rid):
    require_roles(READ)
    return ok_obj(ser(get_or_404("territory_rules", rid)))


@bp.post("/platform/territory-rules/<rid>/lift")
def lift(rid):
    require_roles(["RightsManager"])
    rule = get_or_404("territory_rules", rid)
    svc.lift_rule(rule)
    return ok_obj(ser(rule))
