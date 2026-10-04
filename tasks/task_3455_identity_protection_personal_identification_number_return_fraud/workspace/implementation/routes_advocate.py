"""AdvocateCase routes: open, list, read, expedite (hardship lever), resolve
(with segregation of duties)."""
from flask import Blueprint, request

import calc
from auth import require_roles
from domain import (deadline_plus, get_advocate_case, get_return, get_taxpayer,
                    new_record, open_case_for_return, open_hold_for_return,
                    pub, touch)
from envelope import created, list_response, ok
from errors import err
from store import DB, fmt_ts, parse_ts
from validate import body, opt_str, page, pagination, req_enum, req_str

bp = Blueprint("advocate", __name__)

HARDSHIP_TYPES = ("LEVY_THREAT", "EVICTION", "MEDICAL", "UTILITY_SHUTOFF", "OTHER")


@bp.post("/identity-protection/advocate-cases")
def open_advocate_case():
    uid, role = require_roles(["TaxpayerAdvocate"])
    b = body()
    # Priority 4: body-carried identifiers resolve.
    tid = b.get("taxpayer_id")
    if tid is not None:
        get_taxpayer(tid)
    rid = b.get("return_id")
    if rid is not None:
        get_return(rid)
    # Priority 14: payload shape.
    tid = req_str(b, "taxpayer_id")
    get_taxpayer(tid)
    hardship = req_enum(b, "hardship_type", HARDSHIP_TYPES)
    if rid is not None and not isinstance(rid, str):
        err("ERR_INVALID_REQUEST", "return_id must be a string")
    rec = new_record(DB.advocate_cases, {
        "taxpayer_id": tid,
        "return_id": rid,
        "hardship_type": hardship,
        "expedited": False,
        "opened_by_user_id": uid,
        "resolution_note": "",
        "status": "OPENED",
    })
    return created(pub(rec))


@bp.get("/identity-protection/advocate-cases")
def list_advocate_cases():
    require_roles(["TaxpayerAdvocate", "FraudAnalyst", "SystemAdmin"])
    limit, offset = pagination()
    rows = list(DB.advocate_cases.values())
    for param in ("taxpayer_id", "return_id", "status"):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c.get(param) == v]
    items, total = page(rows, limit, offset)
    return list_response([pub(c) for c in items], total, limit, offset)


@bp.get("/identity-protection/advocate-cases/<string:case_id>")
def read_advocate_case(case_id):
    require_roles(["TaxpayerAdvocate", "FraudAnalyst", "SystemAdmin"])
    return ok(pub(get_advocate_case(case_id)))


@bp.post("/identity-protection/advocate-cases/<string:case_id>/expedite")
def expedite_advocate_case(case_id):
    require_roles(["TaxpayerAdvocate"])
    case = get_advocate_case(case_id)
    if case["status"] == "RESOLVED":
        err("ERR_ALREADY_TERMINAL")
    if case["status"] != "OPENED":
        err("ERR_INVALID_STATE", "Expedite is available only from OPENED.")
    # Priority 11: requires a linked FILTER_HELD return.
    ret = DB.returns.get(case["return_id"]) if case["return_id"] else None
    if ret is None or ret["status"] != "FILTER_HELD":
        err("ERR_HARDSHIP_NOT_EXPEDITABLE")
    case["status"] = "EXPEDITED_REVIEW"
    case["expedited"] = True
    touch(case)
    hold = open_hold_for_return(ret["id"])
    if hold is not None:
        hold["priority_review"] = True
        touch(hold)
    linked = open_case_for_return(ret["id"])
    if linked is not None:
        compressed = deadline_plus(calc.EXPEDITED_CASE_DEADLINE_DAYS)
        if parse_ts(compressed) < parse_ts(linked["deadline_at"]):
            linked["deadline_at"] = compressed
            touch(linked)
    return ok(pub(case))


@bp.post("/identity-protection/advocate-cases/<string:case_id>/resolve")
def resolve_advocate_case(case_id):
    uid, role = require_roles(["TaxpayerAdvocate"])
    case = get_advocate_case(case_id)
    # Priority 3: segregation of duties — the opener may not resolve.
    if case["opened_by_user_id"] == uid:
        err("ERR_DUTY_SEGREGATION_VIOLATION")
    if case["status"] == "RESOLVED":
        err("ERR_ALREADY_TERMINAL")
    note = opt_str(body(), "resolution_note")
    if note is not None:
        case["resolution_note"] = note
    case["status"] = "RESOLVED"
    touch(case)
    return ok(pub(case))
