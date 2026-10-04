"""/survey/panel-enrollments: create, list, read, lifecycle (PRD 3.2)."""
from flask import Blueprint, request

from authz import get_auth, require_role, require_action_role, require_ownership
from bp_programs import find_program_by_code
from calc_alloc import latest_frozen_frame, base_weight_for
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_ESTABLISHMENT_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND, ERR_DUPLICATE_ENROLLMENT,
    ERR_FRAME_NOT_FROZEN, ERR_STRATUM_UNKNOWN, ERR_STRATUM_SAMPLE_FULL,
    ERR_INVALID_STATE, ERR_CASE_STILL_OPEN,
)
from store import DB, new_entity, sorted_entities, touch, NONTERMINAL_ENROLLMENT, LIVE_CASE_STATUSES
from validate import get_body, req_str

bp = Blueprint("enrollments", __name__)

ACTION_ROLES = {
    "ACCEPT": {"Respondent"},
    "DECLINE": {"Respondent"},
    "SUSPEND": {"Respondent", "CollectionOfficer"},
    "REINSTATE": {"CollectionOfficer"},
    "EXIT": {"CollectionOfficer"},
}


@bp.post("/panel-enrollments")
def create_enrollment():
    _user, role = get_auth()
    require_role(role, {"CollectionOfficer"})
    data = get_body()

    # Stage 4: body references.
    establishment = None
    if data.get("establishment_id") is not None:
        establishment = DB["establishments"].get(data["establishment_id"])
        if establishment is None:
            raise_err(ERR_ESTABLISHMENT_NOT_FOUND, "establishment_id does not resolve")
    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")

    # Stage 5: shape.
    req_str(data, "establishment_id")
    req_str(data, "program_code")

    # Stage 11 business constraints: uniqueness, then frame gates, then quota.
    if any(
        e for e in DB["enrollments"].values()
        if e["establishment_id"] == establishment["id"]
        and e["program_code"] == program["code"]
        and e["enrollment_status"] in NONTERMINAL_ENROLLMENT
    ):
        raise_err(ERR_DUPLICATE_ENROLLMENT,
                  "a non-terminal enrollment already exists for this establishment and program")

    frame = latest_frozen_frame(program["code"])
    if frame is None:
        raise_err(ERR_FRAME_NOT_FROZEN, "program has no FROZEN frame")
    weight = base_weight_for(frame, establishment["industry_code"], establishment["size_class"])
    if weight is None:
        raise_err(ERR_STRATUM_UNKNOWN,
                  "establishment's industry/size matches no stratum of the FROZEN frame")
    stratum = next(
        s for s in frame["strata"]
        if s["industry_code"] == establishment["industry_code"]
        and s["size_class"] == establishment["size_class"]
    )
    in_stratum = sum(
        1 for e in DB["enrollments"].values()
        if e["program_code"] == program["code"]
        and e["industry_code"] == establishment["industry_code"]
        and e["size_class"] == establishment["size_class"]
        and e["enrollment_status"] in NONTERMINAL_ENROLLMENT
    )
    if in_stratum >= stratum["allocated_sample_size"]:
        raise_err(ERR_STRATUM_SAMPLE_FULL, "stratum sample quota is exhausted")

    enrollment = new_entity("enrollments", {
        "establishment_id": establishment["id"],
        "program_code": program["code"],
        "industry_code": establishment["industry_code"],
        "size_class": establishment["size_class"],
        "base_weight": weight,
        "burden_minutes_ytd": 0,
        "burden_year": None,
        "enrollment_status": "INVITED",
    })
    return ok(enrollment, status=201)


@bp.get("/panel-enrollments")
def list_enrollments():
    get_auth()
    items = sorted_entities("enrollments")
    for param, field in (("establishment_id", "establishment_id"),
                         ("program_code", "program_code"),
                         ("enrollment_status", "enrollment_status")):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[field] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_enrollment(eid):
    enrollment = DB["enrollments"].get(eid)
    if enrollment is None:
        raise_err(ERR_ENROLLMENT_NOT_FOUND, "panel enrollment not found")
    return enrollment


@bp.get("/panel-enrollments/<eid>")
def get_enrollment(eid):
    get_auth()
    return ok(_load_enrollment(eid))


@bp.post("/panel-enrollments/<eid>/lifecycle")
def lifecycle(eid):
    user, role = get_auth()
    require_role(role, {"Respondent", "CollectionOfficer"})
    # Stage 2 per-action authorization precedes stage 3 path existence
    # (PRD 2.8); peek without raising so a malformed body reports at stage 5.
    peek = request.get_json(silent=True)
    if isinstance(peek, dict):
        require_action_role(role, peek.get("action"), ACTION_ROLES)
    enrollment = _load_enrollment(eid)
    if role == "Respondent":
        require_ownership(user, enrollment["establishment_id"], "enrollment")
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTION_ROLES:
        raise_err(ERR_VALIDATION, f"unknown lifecycle action '{action}'")

    status = enrollment["enrollment_status"]
    target = None
    if action == "ACCEPT" and status == "INVITED":
        target = "ENROLLED"
    elif action == "DECLINE" and status == "INVITED":
        target = "REFUSED"
    elif action == "SUSPEND" and status == "ENROLLED":
        target = "SUSPENDED"
    elif action == "REINSTATE" and status == "SUSPENDED":
        target = "ENROLLED"
    elif action == "EXIT" and status in ("ENROLLED", "SUSPENDED"):
        live = any(
            c for c in DB["cases"].values()
            if c["enrollment_id"] == enrollment["id"]
            and c["case_status"] in LIVE_CASE_STATUSES
        )
        if live:
            raise_err(ERR_CASE_STILL_OPEN,
                      "a follow-up case for this enrollment is still live")
        target = "EXITED"
    if target is None:
        raise_err(ERR_INVALID_STATE,
                  f"cannot perform {action} on an enrollment in {status}")
    enrollment["enrollment_status"] = target
    touch(enrollment)
    return ok(enrollment)
