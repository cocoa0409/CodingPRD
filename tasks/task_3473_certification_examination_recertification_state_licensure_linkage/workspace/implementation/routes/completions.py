"""Program completion records (PRD §3.3): ProgramDirector attestation,
RegistryAdmin verification decision, live attempt-budget counters."""

from flask import Blueprint, request

from db import (STORE, attempts_consumed, attempts_remaining, base_entity,
                now_dt, program_accredited_at_completion, serialize, touch,
                within_validity_window)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, req_enum, req_str)
from util import parse_date

bp = Blueprint("completions", __name__)


def completion_json(r):
    out = serialize(r)
    out["within_validity_window"] = within_validity_window(r)
    out["attempts_consumed"] = attempts_consumed(r["id"])
    out["attempts_remaining"] = attempts_remaining(r["id"])
    return out


@bp.post("/registry/program-completion-records")
def create_completion():
    uid, _ = authn(["ProgramDirector"])
    b = body()
    candidate_id = req_str(b, "candidate_id")
    program_id = req_str(b, "program_id")
    completion_date = parse_date(b.get("completion_date"))
    if completion_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'completion_date' is required and must be an ISO-8601 date")

    candidate = STORE.candidates.get(candidate_id)
    if not candidate:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % candidate_id)
    program = STORE.programs.get(program_id)
    if not program:
        raise_err("ERR_NOT_FOUND", "EducationProgram %s does not exist" % program_id)

    if uid != program["director_user_id"]:
        raise_err("ERR_FORBIDDEN_ROLE",
                  "Only the program's director may attest completions for it")

    from db import accreditation_at
    if accreditation_at(program, completion_date) not in ("ACCREDITED", "PROVISIONAL"):
        raise_err("ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION",
                  "Program accreditation at the completion date was not ACCREDITED or PROVISIONAL")

    e = base_entity()
    e.update({
        "candidate_id": candidate_id,
        "program_id": program_id,
        "completion_date": completion_date,
        "created_by_user_id": uid,
        "status": "PENDING_VERIFICATION",
        "verified_at": None,
        "invalidated_by_case_id": None,
    })
    STORE.completions[e["id"]] = e
    return ok_object(completion_json(e), 201)


@bp.get("/registry/program-completion-records")
def list_completions():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    invalidated_by = request.args.get("invalidated_by_case_id")
    items = []
    for r in STORE.completions.values():
        if candidate_id is not None and r["candidate_id"] != candidate_id:
            continue
        if program_id is not None and r["program_id"] != program_id:
            continue
        if status is not None and r["status"] != status:
            continue
        if invalidated_by is not None and r.get("invalidated_by_case_id") != invalidated_by:
            continue
        items.append(r)
    page, total, limit, offset = list_page(items)
    return ok_list([completion_json(r) for r in page], total, limit, offset)


@bp.get("/registry/program-completion-records/<rid>")
def get_completion(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    r = STORE.completions.get(rid)
    if not r:
        raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist" % rid)
    return ok_object(completion_json(r), 200)


@bp.post("/registry/program-completion-records/<rid>/decision")
def decide_completion(rid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["VERIFIED", "REJECTED"])
    r = STORE.completions.get(rid)
    if not r:
        raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist" % rid)
    if r["status"] != "PENDING_VERIFICATION":
        raise_err("ERR_COMPLETION_NOT_PENDING",
                  "Completion record is %s, not PENDING_VERIFICATION" % r["status"])
    if outcome == "VERIFIED":
        if not program_accredited_at_completion(r):
            raise_err("ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION",
                      "Program accreditation at the completion date was not ACCREDITED or PROVISIONAL")
        r["status"] = "VERIFIED"
        r["verified_at"] = now_dt()
    else:
        r["status"] = "REJECTED"
    touch(r)
    return ok_object(completion_json(r), 200)
