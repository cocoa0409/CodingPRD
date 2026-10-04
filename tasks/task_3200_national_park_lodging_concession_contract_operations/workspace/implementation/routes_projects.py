"""Capital projects."""
from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, paginate, require_fields, req_int, touch)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational
import engine

bp = Blueprint("projects", __name__)

COST_OVERRUN_CAP = 1.10


def get_project(cid, pid):
    p = store.capital_projects.get(pid)
    if not p or p["contract_id"] != cid:
        raise not_found("project")
    return p


@bp.post("/contracts/<cid>/capital-projects")
def create_project(cid):
    require_role("ConcessionerMaintenanceChief")
    c = get_contract(cid)
    require_operational(c)
    body = request.get_json(silent=True)
    require_fields(body, ["title", "asset_ref", "authorized_cost_cents"])
    if not isinstance(body["title"], str) or not body["title"]:
        raise err("ERR_INVALID_REQUEST", 400, "title required")
    if not isinstance(body["asset_ref"], str) or not body["asset_ref"]:
        raise err("ERR_INVALID_REQUEST", 400, "asset_ref required")
    req_int(body, "authorized_cost_cents", minimum=1)
    p = new_entity({
        "contract_id": cid,
        "title": body["title"],
        "asset_ref": body["asset_ref"],
        "authorized_cost_cents": body["authorized_cost_cents"],
        "actual_cost_cents": 0,
        "in_service_month_offset": None,
        "accrued_lsi_cents": 0,
        "status": "PROPOSED",
    })
    store.capital_projects[p["id"]] = p
    return ok(engine.project_out(p), 201)


@bp.get("/contracts/<cid>/capital-projects")
def list_projects(cid):
    require_read_role()
    get_contract(cid)
    items = [p for p in store.capital_projects.values() if p["contract_id"] == cid]
    st = request.args.get("status")
    if st:
        items = [p for p in items if p["status"] == st]
    page, limit, offset, total = paginate(items)
    # recompute live accrual after pagination (order by _seq preserved)
    by_id = {p["id"]: p for p in items}
    page = [engine.project_out(by_id[row["id"]]) for row in page]
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/capital-projects/<pid>")
def get_project_route(cid, pid):
    require_read_role()
    get_contract(cid)
    return ok(engine.project_out(get_project(cid, pid)))


@bp.post("/contracts/<cid>/capital-projects/<pid>/authorize")
def authorize_project(cid, pid):
    require_role("AgencyContractingOfficer")
    get_contract(cid)
    p = get_project(cid, pid)
    if p["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", 409, "Project must be PROPOSED")
    p["status"] = "AUTHORIZED"
    touch(p)
    return ok(engine.project_out(p))


@bp.post("/contracts/<cid>/capital-projects/<pid>/complete")
def complete_project(cid, pid):
    uid, _ = require_role("ConcessionerMaintenanceChief")
    c = get_contract(cid)
    p = get_project(cid, pid)
    if p["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", 409, "Project must be AUTHORIZED")
    body = request.get_json(silent=True)
    require_fields(body, ["actual_cost_cents"])
    actual = req_int(body, "actual_cost_cents", minimum=0)
    if actual > p["authorized_cost_cents"] * COST_OVERRUN_CAP:
        raise err("ERR_COST_OVERRUN", 409, "actual_cost_cents exceeds authorized * 1.10")
    iso = body.get("in_service_month_offset")
    if iso is not None:
        if isinstance(iso, bool) or not isinstance(iso, int) or iso < 0:
            raise err("ERR_INVALID_REQUEST", 400, "in_service_month_offset must be >= 0")
    else:
        iso = engine.current_offset(c)
    p["actual_cost_cents"] = actual
    p["in_service_month_offset"] = iso
    p["status"] = "COMPLETED"
    p["_completed_by_user_id"] = uid
    p["accrued_lsi_cents"] = engine.lsi_accrual(c, p, engine.current_offset(c))
    touch(p)
    return ok(engine.project_out(p))


@bp.post("/contracts/<cid>/capital-projects/<pid>/approve")
def approve_project(cid, pid):
    uid, _ = require_role("AgencyContractingOfficer")
    c = get_contract(cid)
    p = get_project(cid, pid)
    if p["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", 409, "Project must be COMPLETED")
    if p.get("_completed_by_user_id") == uid:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from completer")
    p["status"] = "APPROVED"
    p["accrued_lsi_cents"] = engine.lsi_accrual(c, p, engine.current_offset(c))
    touch(p)
    touch(c)
    return ok(engine.project_out(p))
