"""Environmental incidents."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import new_entity, serialize, paginate, require_fields, parse_dt, touch
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational

bp = Blueprint("incidents", __name__)

CORRECTIVE_PLAN_DAYS = 14


def get_incident(cid, iid):
    i = store.incidents.get(iid)
    if not i or i["contract_id"] != cid:
        raise not_found("incident")
    return i


@bp.post("/contracts/<cid>/environmental-incidents")
def create_incident(cid):
    require_role("ConcessionerOpsManager", "AgencyEnvironmentalInspector")
    c = get_contract(cid)
    require_operational(c)
    body = request.get_json(silent=True)
    require_fields(body, ["protocol", "severity", "occurred_at", "description"])
    if body["protocol"] not in ("WASTE", "WATER", "WILDLIFE"):
        raise err("ERR_INVALID_REQUEST", 400, "invalid protocol")
    if body["severity"] not in ("MINOR", "MAJOR", "CRITICAL"):
        raise err("ERR_INVALID_REQUEST", 400, "invalid severity")
    occ = parse_dt(body["occurred_at"], "occurred_at")
    if not isinstance(body["description"], str):
        raise err("ERR_INVALID_REQUEST", 400, "description required")
    deadline = occ + timedelta(days=CORRECTIVE_PLAN_DAYS)
    i = new_entity({
        "contract_id": cid,
        "protocol": body["protocol"],
        "severity": body["severity"],
        "occurred_at": body["occurred_at"],
        "description": body["description"],
        "corrective_plan_deadline": deadline.strftime("%Y-%m-%dT%H:%M:%S.") + f"{deadline.microsecond // 1000:03d}Z",
        "status": "REPORTED",
    })
    store.incidents[i["id"]] = i
    return ok(serialize(i), 201)


@bp.get("/contracts/<cid>/environmental-incidents")
def list_incidents(cid):
    require_read_role()
    get_contract(cid)
    items = [i for i in store.incidents.values() if i["contract_id"] == cid]
    for key in ("protocol", "severity", "status"):
        v = request.args.get(key)
        if v:
            items = [i for i in items if str(i.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/environmental-incidents/<iid>/start-review")
def start_review(cid, iid):
    require_role("AgencyEnvironmentalInspector")
    get_contract(cid)
    i = get_incident(cid, iid)
    if i["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", 409, "Incident must be REPORTED")
    i["status"] = "UNDER_REVIEW"
    touch(i)
    return ok(serialize(i))


@bp.post("/contracts/<cid>/environmental-incidents/<iid>/require-corrective-plan")
def require_plan(cid, iid):
    require_role("AgencyEnvironmentalInspector")
    get_contract(cid)
    i = get_incident(cid, iid)
    if i["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Incident must be UNDER_REVIEW")
    i["status"] = "CORRECTIVE_PLAN_REQUIRED"
    touch(i)
    return ok(serialize(i))


@bp.post("/contracts/<cid>/environmental-incidents/<iid>/submit-corrective-plan")
def submit_plan(cid, iid):
    require_role("ConcessionerOpsManager")
    get_contract(cid)
    i = get_incident(cid, iid)
    if i["status"] != "CORRECTIVE_PLAN_REQUIRED":
        raise err("ERR_INVALID_STATE", 409, "Incident must be CORRECTIVE_PLAN_REQUIRED")
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("plan_text"), str) or not body["plan_text"]:
        raise err("ERR_INVALID_REQUEST", 400, "plan_text required")
    if store.clock > parse_dt(i["corrective_plan_deadline"]):
        raise err("ERR_CORRECTIVE_PLAN_LATE", 409, "Corrective plan submitted after the deadline")
    i["status"] = "UNDER_REVIEW"
    touch(i)
    return ok(serialize(i))


@bp.post("/contracts/<cid>/environmental-incidents/<iid>/close")
def close_incident(cid, iid):
    require_role("AgencyEnvironmentalInspector")
    get_contract(cid)
    i = get_incident(cid, iid)
    if i["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Incident must be UNDER_REVIEW")
    i["status"] = "CLOSED"
    touch(i)
    return ok(serialize(i))
