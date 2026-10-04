"""Psychomotor verifications (PRD §3.5): polymorphic submission
(ProgramDirector/PROGRAM, StateOfficial/STATE), segregation of duties,
duplicate-window containment, admin decision."""

from flask import Blueprint, request

from db import STORE, base_entity, now_dt, serialize, touch
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_str,
                        req_bool, req_enum, req_list, req_str)
from util import add_months_date, parse_date

bp = Blueprint("psychomotor", __name__)


@bp.post("/registry/psychomotor-verifications")
def create_psychomotor():
    uid, role = authn(["ProgramDirector", "StateOfficial"])
    b = body()
    candidate_id = req_str(b, "candidate_id")
    level_id = req_str(b, "level_id")
    administered_by = req_enum(b, "administered_by", ["PROGRAM", "STATE"])
    completion_record_id = req_str(b, "completion_record_id")
    exam_date = parse_date(b.get("exam_date"))
    stations = req_list(b, "stations")
    documentation_attached = req_bool(b, "documentation_attached")
    program_id = b.get("program_id")

    # Role binding: ProgramDirector submits PROGRAM records, StateOfficial STATE.
    if administered_by == "PROGRAM" and role != "ProgramDirector":
        raise_err("ERR_FORBIDDEN_ROLE",
                  "PROGRAM-administered verifications are submitted by a ProgramDirector")
    if administered_by == "STATE" and role != "StateOfficial":
        raise_err("ERR_FORBIDDEN_ROLE",
                  "STATE-administered verifications are submitted by a StateOfficial")

    # Shape: program_id required iff PROGRAM, forbidden otherwise.
    if administered_by == "PROGRAM":
        if not isinstance(program_id, str) or not program_id:
            raise_err("ERR_INVALID_REQUEST",
                      "program_id is required when administered_by is PROGRAM")
    elif program_id is not None:
        raise_err("ERR_INVALID_REQUEST",
                  "program_id is forbidden when administered_by is STATE")

    if exam_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'exam_date' must be an ISO-8601 date")
    if exam_date > now_dt().date():
        raise_err("ERR_INVALID_REQUEST", "exam_date may not lie in the future")
    if not stations:
        raise_err("ERR_INVALID_REQUEST", "stations must be a non-empty array")
    for i, s in enumerate(stations):
        if (not isinstance(s, dict)
                or not isinstance(s.get("station_code"), str)
                or not s.get("station_code")
                or not isinstance(s.get("passed"), bool)):
            raise_err("ERR_INVALID_REQUEST",
                      "stations[%d] must pair a station_code with a boolean passed flag" % i)

    candidate = STORE.candidates.get(candidate_id)
    if not candidate:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % candidate_id)
    if level_id not in STORE.levels:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)
    record = STORE.completions.get(completion_record_id)
    if not record:
        raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist" % completion_record_id)
    program = None
    if program_id is not None:
        program = STORE.programs.get(program_id)
        if not program:
            raise_err("ERR_NOT_FOUND", "EducationProgram %s does not exist" % program_id)

    if program is not None and uid != program["director_user_id"]:
        raise_err("ERR_FORBIDDEN_ROLE",
                  "Only the program's director may submit its psychomotor verifications")

    # Segregation of duties: the PROGRAM evaluator must differ from the
    # director who attested the cited completion record.
    if administered_by == "PROGRAM" and uid == record["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The evaluator may not be the director who attested the completion record")

    # Cross-record consistency: the completion record must belong to the same
    # candidate and level (and a named program must teach the level).
    record_program = STORE.programs.get(record["program_id"])
    if record["candidate_id"] != candidate_id:
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Completion record belongs to a different candidate")
    if record_program and record_program["level_id"] != level_id:
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Completion record teaches a different level")
    if program is not None and program["level_id"] != level_id:
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "The named program teaches a different level")

    # Duplicate-window containment: VERIFIED windows are
    # [date(verified_at), add_months(verified_at, 24)) — half-open.
    for pv in STORE.psychomotors.values():
        if (pv["candidate_id"] == candidate_id and pv["level_id"] == level_id
                and pv["status"] == "VERIFIED" and pv.get("verified_at")):
            w_start = pv["verified_at"].date()
            w_end = add_months_date(w_start, 24)
            if w_start <= exam_date < w_end:
                raise_err("ERR_ACTIVE_VERIFICATION_EXISTS",
                          "exam_date falls inside an existing VERIFIED window")

    e = base_entity()
    e.update({
        "candidate_id": candidate_id,
        "level_id": level_id,
        "administered_by": administered_by,
        "program_id": program_id,
        "evaluator_user_id": uid,
        "completion_record_id": completion_record_id,
        "exam_date": exam_date,
        "stations": stations,
        "documentation_attached": documentation_attached,
        "status": "SUBMITTED",
        "verified_at": None,
    })
    STORE.psychomotors[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/psychomotor-verifications")
def list_psychomotors():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    level_id = request.args.get("level_id")
    program_id = request.args.get("program_id")
    completion_record_id = request.args.get("completion_record_id")
    status = request.args.get("status")
    items = []
    for pv in STORE.psychomotors.values():
        if candidate_id is not None and pv["candidate_id"] != candidate_id:
            continue
        if level_id is not None and pv["level_id"] != level_id:
            continue
        if program_id is not None and pv.get("program_id") != program_id:
            continue
        if completion_record_id is not None and pv["completion_record_id"] != completion_record_id:
            continue
        if status is not None and pv["status"] != status:
            continue
        items.append(pv)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(pv) for pv in page], total, limit, offset)


@bp.get("/registry/psychomotor-verifications/<pid>")
def get_psychomotor(pid):
    authn(ALL_AUTHENTICATED_ROLES)
    pv = STORE.psychomotors.get(pid)
    if not pv:
        raise_err("ERR_NOT_FOUND", "PsychomotorVerification %s does not exist" % pid)
    return ok_object(serialize(pv), 200)


@bp.post("/registry/psychomotor-verifications/<pid>/decision")
def decide_psychomotor(pid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["VERIFIED", "REJECTED"])
    pv = STORE.psychomotors.get(pid)
    if not pv:
        raise_err("ERR_NOT_FOUND", "PsychomotorVerification %s does not exist" % pid)
    if pv["status"] != "SUBMITTED":
        raise_err("ERR_PSYCHOMOTOR_NOT_SUBMITTED",
                  "Psychomotor verification is %s, not SUBMITTED" % pv["status"])
    if outcome == "VERIFIED":
        if not (all(s["passed"] for s in pv["stations"]) and pv["documentation_attached"]):
            raise_err("ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET",
                      "Verification requires all stations passed and documentation attached")
        pv["status"] = "VERIFIED"
        pv["verified_at"] = now_dt()
    else:
        pv["status"] = "REJECTED"
    touch(pv)
    return ok_object(serialize(pv), 200)
