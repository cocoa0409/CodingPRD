"""SupportiveMeasure endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE_TRANSITION, ERR_SUPPORTIVE_MEASURE_CONFIDENTIAL
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    MEASURE_TYPES, MEASURE_SIDES,
)
from validate import get_body, req_str, req_enum, req_datetime, opt_datetime, require_path

bp = Blueprint("measures", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


def _party_visible_measure(measure, case, caller):
    """Tier 5 confidentiality for single reads by Party callers."""
    if caller.role == "Party":
        side = party_side_of(case, caller.user_id)
        if measure["party_side"] not in ("BOTH", side):
            raise_error(ERR_SUPPORTIVE_MEASURE_CONFIDENTIAL,
                        "measure is scoped to the other party")


@bp.post("/cases/<cid>/supportive-measures")
def create_measure(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    measure_type = req_enum(body, "measure_type", MEASURE_TYPES)
    party_side = req_enum(body, "party_side", MEASURE_SIDES)
    description = req_str(body, "description")
    effective_from = req_datetime(body, "effective_from")
    effective_to = opt_datetime(body, "effective_to")
    rec = new_record("supportive_measures", {
        "case_id": cid,
        "measure_type": measure_type,
        "party_side": party_side,
        "description": description,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "is_confidential": True,
        "status": "ACTIVE",
    })
    case["active_supportive_measure_count"] += 1
    bump_case(case)
    append_event(cid, "MEASURE_CREATED", caller,
                 {"measure_id": rec["id"], "measure_type": measure_type, "status": "ACTIVE"})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/supportive-measures")
def list_measures(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [m for m in db["supportive_measures"].values() if m["case_id"] == cid]
    if caller.role == "Party":
        side = party_side_of(case, caller.user_id)
        items = [m for m in items if m["party_side"] in ("BOTH", side)]
    items = apply_filters(items, {
        "status": request.args.get("status"),
        "party_side": request.args.get("party_side"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/supportive-measures/<mid>")
def get_measure(mid):
    caller = authorized(READ_ROLES)
    measure = require_path("supportive_measures", mid)
    case = get_case(measure["case_id"])
    check_case_read_access(caller, case)
    _party_visible_measure(measure, case, caller)
    return success_object(public(measure))


@bp.post("/supportive-measures/<mid>/terminate")
def terminate_measure(mid):
    caller = authorized(["TitleIXCoordinator"])
    measure = require_path("supportive_measures", mid)
    if measure["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"measure is {measure['status']}, not ACTIVE")
    case = get_case(measure["case_id"])
    measure["status"] = "TERMINATED"
    touch(measure)
    case["active_supportive_measure_count"] -= 1
    bump_case(case)
    append_event(measure["case_id"], "MEASURE_TERMINATED", caller,
                 {"measure_id": mid, "status": "TERMINATED"})
    return success_object(public(measure))
