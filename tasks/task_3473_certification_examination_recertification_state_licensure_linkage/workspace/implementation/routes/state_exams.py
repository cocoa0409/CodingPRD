"""State exam records (PRD §3.8): StateOfficial registers a state's own
examination result; passed computed; VOIDED by severe discipline."""

from flask import Blueprint, request

from db import STORE, base_entity, now_dt, serialize
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, req_number,
                        req_str)
from util import parse_date

bp = Blueprint("state_exams", __name__)


def state_exam_json(r):
    out = serialize(r)
    out["passed"] = float(r["score"]) >= float(r["passing_score"])
    return out


@bp.post("/registry/state-exam-records")
def create_state_exam():
    authn(["StateOfficial"])
    b = body()
    candidate_id = req_str(b, "candidate_id")
    state_code = req_str(b, "state_code")
    level_id = req_str(b, "level_id")
    exam_date = parse_date(b.get("exam_date"))
    score = req_number(b, "score")
    passing_score = req_number(b, "passing_score")

    if exam_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'exam_date' must be an ISO-8601 date")
    if exam_date > now_dt().date():
        raise_err("ERR_INVALID_REQUEST", "exam_date may not lie in the future")

    if candidate_id not in STORE.candidates:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % candidate_id)
    if level_id not in STORE.levels:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)

    e = base_entity()
    e.update({
        "candidate_id": candidate_id,
        "state_code": state_code,
        "level_id": level_id,
        "exam_date": exam_date,
        "score": score,
        "passing_score": passing_score,
        "passed": float(score) >= float(passing_score),
        "status": "VALID",
        "voided_by_case_id": None,
    })
    STORE.state_exams[e["id"]] = e
    return ok_object(state_exam_json(e), 201)


@bp.get("/registry/state-exam-records")
def list_state_exams():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    state_code = request.args.get("state_code")
    level_id = request.args.get("level_id")
    status = request.args.get("status")
    voided_by = request.args.get("voided_by_case_id")
    items = []
    for r in STORE.state_exams.values():
        if candidate_id is not None and r["candidate_id"] != candidate_id:
            continue
        if state_code is not None and r["state_code"] != state_code:
            continue
        if level_id is not None and r["level_id"] != level_id:
            continue
        if status is not None and r["status"] != status:
            continue
        if voided_by is not None and r.get("voided_by_case_id") != voided_by:
            continue
        items.append(r)
    page, total, limit, offset = list_page(items)
    return ok_list([state_exam_json(r) for r in page], total, limit, offset)


@bp.get("/registry/state-exam-records/<rid>")
def get_state_exam(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    r = STORE.state_exams.get(rid)
    if not r:
        raise_err("ERR_NOT_FOUND", "StateExamRecord %s does not exist" % rid)
    return ok_object(state_exam_json(r), 200)
