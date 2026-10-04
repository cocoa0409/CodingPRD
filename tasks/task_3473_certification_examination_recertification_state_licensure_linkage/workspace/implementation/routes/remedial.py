"""Remedial education records (PRD §3.4): ProgramDirector attestation gating
cognitive attempts 4-6. The record is verified at creation."""

from flask import Blueprint, request

from db import STORE, base_entity, serialize
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, req_number,
                        req_str)
from util import is_half_increment, parse_date

bp = Blueprint("remedial", __name__)


@bp.post("/registry/remedial-education-records")
def create_remedial():
    uid, _ = authn(["ProgramDirector"])
    b = body()
    candidate_id = req_str(b, "candidate_id")
    level_id = req_str(b, "level_id")
    hours = req_number(b, "hours")
    completed_date = parse_date(b.get("completed_date"))
    provider_name = req_str(b, "provider_name")

    if not is_half_increment(hours):
        raise_err("ERR_INVALID_REQUEST",
                  "hours must be positive and in 0.5-hour increments")
    if completed_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'completed_date' must be an ISO-8601 date")

    if candidate_id not in STORE.candidates:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % candidate_id)
    if level_id not in STORE.levels:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)

    e = base_entity()
    e.update({
        "candidate_id": candidate_id,
        "level_id": level_id,
        "hours": hours,
        "completed_date": completed_date,
        "provider_name": provider_name,
        "attested_by_user_id": uid,
    })
    STORE.remedials[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/remedial-education-records")
def list_remedial():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    level_id = request.args.get("level_id")
    items = []
    for r in STORE.remedials.values():
        if candidate_id is not None and r["candidate_id"] != candidate_id:
            continue
        if level_id is not None and r["level_id"] != level_id:
            continue
        items.append(r)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.get("/registry/remedial-education-records/<rid>")
def get_remedial(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    r = STORE.remedials.get(rid)
    if not r:
        raise_err("ERR_NOT_FOUND", "RemedialEducationRecord %s does not exist" % rid)
    return ok_object(serialize(r), 200)
