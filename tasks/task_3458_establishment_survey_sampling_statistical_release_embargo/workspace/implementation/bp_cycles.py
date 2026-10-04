"""/survey/survey-cycles: create, list, advance (PRD 3.3, 3.5)."""
from datetime import datetime, timezone
from flask import Blueprint, request

from authz import get_auth, require_role, require_action_role
from bp_programs import find_program_by_code
from calc_apply import flag_published_release
from calc_est import compute_estimates
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_PROGRAM_NOT_FOUND, ERR_CYCLE_NOT_FOUND,
    ERR_DUPLICATE_CYCLE, ERR_INVALID_STATE, ERR_CYCLE_WINDOW_VIOLATION,
    ERR_ESTIMATES_NOT_COMPUTED, ERR_RESPONSE_RATE_BELOW_MINIMUM,
)
from store import (
    DB, new_entity, sorted_entities, touch, now,
    COLLECTION_CLOSE_DAY, MIN_WEIGHTED_RESPONSE_RATE,
)
from validate import get_body, req_str, parse_month_field, month_str

bp = Blueprint("cycles", __name__)

ACTION_ROLES = {
    "OPEN_COLLECTION": {"CollectionOfficer"},
    "CLOSE_COLLECTION": {"CollectionOfficer"},
    "COMPUTE_ESTIMATES": {"EstimationAnalyst"},
    "CERTIFY": {"EstimationAnalyst"},
    "REOPEN_REVISION": {"EstimationAnalyst"},
}


@bp.post("/survey-cycles")
def create_cycle():
    _user, role = get_auth()
    require_role(role, {"ProgramAdmin"})
    data = get_body()

    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")

    req_str(data, "program_code")
    mref = parse_month_field(data, "reference_month")
    ref = month_str(mref)

    if any(c for c in DB["cycles"].values()
           if c["program_code"] == program["code"] and c["reference_month"] == ref):
        raise_err(ERR_DUPLICATE_CYCLE,
                  "a cycle already exists for this program and reference_month")

    year, month = mref
    cycle = new_entity("cycles", {
        "program_code": program["code"],
        "reference_month": ref,
        "collection_open_at": datetime(year, month, 1, tzinfo=timezone.utc),
        "collection_close_at": datetime(year, month, COLLECTION_CLOSE_DAY,
                                        23, 59, 59, tzinfo=timezone.utc),
        "cycle_status": "SCHEDULED",
        "estimates_computed_at": None,
        "weighted_response_rate": None,
        "unweighted_response_rate": None,
        "certified_by_user_id": None,
    })
    return ok(cycle, status=201)


@bp.get("/survey-cycles")
def list_cycles():
    get_auth()
    items = sorted_entities("cycles")
    for param in ("program_code", "cycle_status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_cycle(cid):
    cycle = DB["cycles"].get(cid)
    if cycle is None:
        raise_err(ERR_CYCLE_NOT_FOUND, "survey cycle not found")
    return cycle


def _close_collection(cycle):
    """Side effects: open a FollowUpCase per ENROLLED enrollment without an
    ACCEPTED report for this cycle; clear estimates_computed_at."""
    accepted_enrollment_ids = {
        r["enrollment_id"] for r in DB["reports"].values()
        if r["cycle_id"] == cycle["id"] and r["report_status"] == "ACCEPTED"
    }
    for enr in DB["enrollments"].values():
        if enr["program_code"] != cycle["program_code"]:
            continue
        if enr["enrollment_status"] != "ENROLLED":
            continue
        if enr["id"] in accepted_enrollment_ids:
            continue
        new_entity("cases", {
            "enrollment_id": enr["id"],
            "cycle_id": cycle["id"],
            "case_status": "OPEN",
            "opened_at": now(),
            "contacts": [],
            "total_contact_minutes": 0,
        })
    cycle["estimates_computed_at"] = None
    cycle["cycle_status"] = "PROCESSING"
    touch(cycle)


def _certify(cycle, user):
    if cycle["estimates_computed_at"] is None:
        raise_err(ERR_ESTIMATES_NOT_COMPUTED,
                  "estimates have not been computed since the last close/reopen")
    rate = cycle["weighted_response_rate"]
    if rate is None or rate < MIN_WEIGHTED_RESPONSE_RATE:
        raise_err(ERR_RESPONSE_RATE_BELOW_MINIMUM,
                  "weighted_response_rate is below 0.600000")
    cycle["certified_by_user_id"] = user
    if cycle["cycle_status"] == "REVISION_OPEN":
        published_release = any(
            r for r in DB["releases"].values()
            if r["cycle_id"] == cycle["id"] and r["pub_status"] == "PUBLISHED"
        )
        cycle["cycle_status"] = "PUBLISHED" if published_release else "CERTIFIED"
    else:
        cycle["cycle_status"] = "CERTIFIED"
    touch(cycle)


@bp.post("/survey-cycles/<cid>/advance")
def advance_cycle(cid):
    user, role = get_auth()
    require_role(role, {"CollectionOfficer", "EstimationAnalyst"})
    # Stage 2 per-action authorization precedes stage 3 path existence
    # (PRD 2.8); peek without raising so a malformed body reports at stage 5.
    peek = request.get_json(silent=True)
    if isinstance(peek, dict):
        require_action_role(role, peek.get("action"), ACTION_ROLES)
    cycle = _load_cycle(cid)
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTION_ROLES:
        raise_err(ERR_VALIDATION, f"unknown cycle action '{action}'")

    status = cycle["cycle_status"]
    clock = now()

    if action == "OPEN_COLLECTION":
        if status != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, f"cannot open collection from {status}")
        if clock < cycle["collection_open_at"]:
            raise_err(ERR_CYCLE_WINDOW_VIOLATION,
                      "collection window has not opened yet")
        cycle["cycle_status"] = "COLLECTING"
        touch(cycle)
    elif action == "CLOSE_COLLECTION":
        if status != "COLLECTING":
            raise_err(ERR_INVALID_STATE, f"cannot close collection from {status}")
        if clock < cycle["collection_close_at"]:
            raise_err(ERR_CYCLE_WINDOW_VIOLATION,
                      "collection window has not closed yet")
        _close_collection(cycle)
    elif action == "COMPUTE_ESTIMATES":
        if status not in ("PROCESSING", "REVISION_OPEN"):
            raise_err(ERR_INVALID_STATE, f"cannot compute estimates from {status}")
        compute_estimates(cycle)
    elif action == "CERTIFY":
        if status not in ("PROCESSING", "REVISION_OPEN"):
            raise_err(ERR_INVALID_STATE, f"cannot certify from {status}")
        _certify(cycle, user)
    elif action == "REOPEN_REVISION":
        if status != "PUBLISHED":
            raise_err(ERR_INVALID_STATE, f"cannot reopen revision from {status}")
        cycle["estimates_computed_at"] = None
        cycle["cycle_status"] = "REVISION_OPEN"
        touch(cycle)
        flag_published_release(cycle["id"])
    return ok(cycle)
