"""Education programs and accreditation events (PRD §3.2). REVOKED fires the
five-hop program-revocation cascade."""

from flask import Blueprint, request

from db import STORE, base_entity, now_dt, serialize, touch
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, req_enum,
                        req_str)
from services.cascade import program_revocation_cascade
from util import parse_datetime

bp = Blueprint("programs", __name__)

ACCREDITATION_STATUSES = ["ACCREDITED", "PROVISIONAL", "SUSPENDED", "REVOKED"]
ALLOWED_TRANSITIONS = {
    "ACCREDITED": {"PROVISIONAL", "SUSPENDED", "REVOKED"},
    "PROVISIONAL": {"ACCREDITED", "SUSPENDED", "REVOKED"},
    "SUSPENDED": {"ACCREDITED", "REVOKED"},
    "REVOKED": set(),
}


@bp.post("/registry/education-programs")
def create_program():
    authn(["RegistryAdmin"])
    b = body()
    name = req_str(b, "name")
    level_id = req_str(b, "level_id")
    director_user_id = req_str(b, "director_user_id")
    if level_id not in STORE.levels:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)

    e = base_entity()
    now = now_dt()
    e.update({
        "name": name,
        "level_id": level_id,
        "director_user_id": director_user_id,
        "accreditation_status": "ACCREDITED",
        "accreditation_history": [{
            "to_status": "ACCREDITED",
            "effective_date": now,
            "recorded_at": now,
            "reason": None,
        }],
    })
    STORE.programs[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/education-programs")
def list_programs():
    authn(ALL_AUTHENTICATED_ROLES)
    level_id = request.args.get("level_id")
    items = [e for e in STORE.programs.values()
             if level_id is None or e["level_id"] == level_id]
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(e) for e in page], total, limit, offset)


@bp.get("/registry/education-programs/<pid>")
def get_program(pid):
    authn(ALL_AUTHENTICATED_ROLES)
    p = STORE.programs.get(pid)
    if not p:
        raise_err("ERR_NOT_FOUND", "EducationProgram %s does not exist" % pid)
    return ok_object(serialize(p), 200)


@bp.post("/registry/education-programs/<pid>/accreditation-events")
def accreditation_event(pid):
    authn(["RegistryAdmin"])
    b = body()
    to_status = req_enum(b, "to_status", ACCREDITATION_STATUSES)
    effective_date = parse_datetime(b.get("effective_date"))
    if effective_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'effective_date' is required and must be an ISO-8601 date or timestamp")
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise_err("ERR_INVALID_REQUEST", "Field 'reason' must be a string")
    p = STORE.programs.get(pid)
    if not p:
        raise_err("ERR_NOT_FOUND", "EducationProgram %s does not exist" % pid)

    if to_status not in ALLOWED_TRANSITIONS[p["accreditation_status"]]:
        raise_err("ERR_INVALID_STATE",
                  "Accreditation transition %s -> %s is not permitted"
                  % (p["accreditation_status"], to_status))

    p["accreditation_history"].append({
        "to_status": to_status,
        "effective_date": effective_date,
        "recorded_at": now_dt(),
        "reason": reason,
    })
    p["accreditation_status"] = to_status
    touch(p)
    if to_status == "REVOKED":
        program_revocation_cascade(p, effective_date)
    return ok_object(serialize(p), 200)
