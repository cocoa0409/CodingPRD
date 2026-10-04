"""Suppliers and collection programs."""
from flask import Blueprint

import db as dbmod
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from services.lookup import get_path, get_body_ref, single_plant
from services.review import recompute_supplier_tier
from util import body, ok_object, ok_list, req_int, req_str, new_resource, touch

bp = Blueprint("suppliers", __name__)


@bp.post("/decking/suppliers")
@require_roles("QualityEngineer")
def create_supplier():
    data = body()
    name = req_str(data, "name")
    kind = data.get("kind")
    if kind not in ("COLLECTION_PROGRAM", "BROKER"):
        raise_err(ERR_INVALID_REQUEST, "kind must be COLLECTION_PROGRAM or BROKER")
    s = new_resource({
        "name": name,
        "kind": kind,
        "quality_tier": "STANDARD",
        "reliability_score_bp": 10000,
    })
    dbmod.db.suppliers[s["id"]] = s
    return ok_object(dict(s), status=201)


@bp.get("/decking/suppliers/<sid>")
@require_roles("QualityEngineer", "OpsManager", "ChannelManager")
def get_supplier(sid):
    return ok_object(dict(get_path("suppliers", sid)))


@bp.get("/decking/suppliers/<sid>/collection-programs")
@require_roles("QualityEngineer", "ChannelManager")
def list_supplier_programs(sid):
    get_path("suppliers", sid)
    items = [dict(p) for p in dbmod.db.collection_programs.values() if p["supplier_id"] == sid]
    return ok_list(items)


@bp.get("/decking/suppliers/<sid>/feedstock-lots")
@require_roles("QualityEngineer", "OpsManager")
def list_supplier_lots(sid):
    get_path("suppliers", sid)
    items = [dict(l) for l in dbmod.db.feedstock_lots.values() if l["supplier_id"] == sid]
    return ok_list(items)


@bp.post("/decking/collection-programs")
@require_roles("ChannelManager")
def create_program():
    data = body()
    sup = get_body_ref("suppliers", data.get("supplier_id"), "supplier_id")
    region = req_str(data, "region")
    rebate = req_int(data, "rebate_per_lb_cents", minimum=0)
    p = new_resource({
        "supplier_id": sup["id"],
        "region": region,
        "rebate_per_lb_cents": rebate,
        "accrued_rebate_cents": 0,
        "status": "ACTIVE",
    })
    dbmod.db.collection_programs[p["id"]] = p
    recompute_supplier_tier(sup["id"])
    return ok_object(dict(p), status=201)


@bp.get("/decking/collection-programs/<pid>")
@require_roles("ChannelManager", "QualityEngineer")
def get_program(pid):
    return ok_object(dict(get_path("collection_programs", pid)))


def _program_transition(pid, allowed_from, to):
    p = get_path("collection_programs", pid)
    if p["status"] not in allowed_from:
        raise_err(ERR_INVALID_STATE, f"program is {p['status']}")
    p["status"] = to
    touch(p)
    recompute_supplier_tier(p["supplier_id"])
    return ok_object(dict(p))


@bp.post("/decking/collection-programs/<pid>/suspend")
@require_roles("ChannelManager")
def suspend_program(pid):
    return _program_transition(pid, ("ACTIVE",), "SUSPENDED")


@bp.post("/decking/collection-programs/<pid>/reactivate")
@require_roles("ChannelManager")
def reactivate_program(pid):
    return _program_transition(pid, ("SUSPENDED",), "ACTIVE")


@bp.post("/decking/collection-programs/<pid>/terminate")
@require_roles("ChannelManager")
def terminate_program(pid):
    return _program_transition(pid, ("ACTIVE", "SUSPENDED"), "TERMINATED")
