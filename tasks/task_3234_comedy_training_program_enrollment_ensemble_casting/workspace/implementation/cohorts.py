"""CohortProgram routes."""
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE,
    ERR_COHORT_OVER_CAPACITY, ERR_MIN_TRACK_LEVEL_NOT_MET,
)
from services import refresh_student_derived

bp = Blueprint("cohorts", __name__)

ROLES = ["ProgramDirector", "CastingDirector", "Registrar", "Student"]
KINDS = {"CONSERVATORY", "INTENSIVE"}
TRACKS = {"IMPROV", "SKETCH", "STANDUP", "CONSERVATORY"}


def _get(cid):
    c = store.cohorts.get(cid)
    if not c:
        not_found("cohort not found")
    return c


@bp.post("/cohort-programs")
def create_cohort():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["kind", "track", "term_id", "cohort_size", "min_track_level_code"])
    if body["kind"] not in KINDS:
        invalid_request("invalid kind")
    if body["track"] not in TRACKS:
        invalid_request("invalid track")
    if body["term_id"] not in store.terms:
        not_found("term not found")
    if not isinstance(body["cohort_size"], int) or isinstance(body["cohort_size"], bool) or body["cohort_size"] <= 0:
        invalid_request("cohort_size must be a positive integer")
    c = fresh({
        "kind": body["kind"],
        "track": body["track"],
        "term_id": body["term_id"],
        "cohort_size": body["cohort_size"],
        "admitted_count": 0,
        "requires_audition": bool(body.get("requires_audition", True)),
        "min_track_level_code": body["min_track_level_code"],
        "status": "FORMING",
        "_admitted_ids": [],
        # cast track resolution for the touring understudy coverage predicate
        # (§3.9): cohort-cast students are credited in the cohort's track
        "_track": body["track"],
    })
    store.cohorts[c["id"]] = c
    return success_obj(c, 201)


@bp.get("/cohort-programs")
def list_cohorts():
    auth(ROLES)
    limit, offset = pagination_params()
    items = list(store.cohorts.values())
    if request.args.get("term_id"):
        items = [x for x in items if x["term_id"] == request.args["term_id"]]
    if request.args.get("kind"):
        items = [x for x in items if x["kind"] == request.args["kind"]]
    if request.args.get("status"):
        items = [x for x in items if x["status"] == request.args["status"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/cohort-programs/<cid>")
def get_cohort(cid):
    auth(ROLES)
    return success_obj(_get(cid))


@bp.post("/cohort-programs/<cid>/begin-auditions")
def begin_auditions(cid):
    auth(["ProgramDirector"])
    c = _get(cid)
    if c["status"] != "FORMING":
        raise_err(ERR_INVALID_STATE, "cohort must be FORMING")
    c["status"] = "AUDITIONING"
    stamp(c)
    return success_obj(c)


@bp.post("/cohort-programs/<cid>/admit")
def admit(cid):
    auth(["ProgramDirector"])
    c = _get(cid)
    if c["status"] not in ("AUDITIONING",):
        raise_err(ERR_INVALID_STATE, "cohort must be AUDITIONING")
    body = json_body()
    require_fields(body, ["audition_id"])
    audition = store.auditions.get(body["audition_id"])
    if not audition:
        not_found("audition not found")
    if audition.get("cohort_program_id") != c["id"] or audition["target_kind"] != "COHORT":
        invalid_request("audition does not target this cohort")
    if audition["outcome"] not in ("EVALUATED", "WAITLISTED"):
        raise_err(ERR_INVALID_STATE, "audition must be EVALUATED or WAITLISTED")
    if c["admitted_count"] >= c["cohort_size"]:
        raise_err(ERR_COHORT_OVER_CAPACITY, "cohort is at capacity")
    student = store.students.get(audition["student_id"])
    if not student:
        not_found("student not found")
    if c["min_track_level_code"] not in (student.get("completed_level_codes") or []) \
            and c["min_track_level_code"] not in (student.get("placement_credit_codes") or []):
        raise_err(ERR_MIN_TRACK_LEVEL_NOT_MET, "student lacks min track level")
    audition["outcome"] = "SELECTED"
    stamp(audition)
    c["admitted_count"] += 1
    c["_admitted_ids"].append(student["id"])
    stamp(c)
    return success_obj(c)


@bp.post("/cohort-programs/<cid>/finalize-cohort")
def finalize(cid):
    auth(["ProgramDirector"])
    c = _get(cid)
    if c["status"] != "AUDITIONING":
        raise_err(ERR_INVALID_STATE, "cohort must be AUDITIONING")
    if not (1 <= c["admitted_count"] <= c["cohort_size"]):
        raise_err(ERR_INVALID_STATE, "admitted_count must be between 1 and cohort_size")
    c["status"] = "CASTED"
    stamp(c)
    return success_obj(c)


@bp.post("/cohort-programs/<cid>/graduate")
def graduate(cid):
    auth(["ProgramDirector"])
    c = _get(cid)
    if c["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "cohort must be ACTIVE")
    term = store.terms.get(c["term_id"])
    if not term or term["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "term must be CLOSED")
    c["status"] = "GRADUATED"
    stamp(c)
    for sid in c.get("_admitted_ids", []):
        stu = store.students.get(sid)
        if stu:
            refresh_student_derived(stu)
            stamp(stu)
    return success_obj(c)


@bp.post("/cohort-programs/<cid>/dissolve")
def dissolve(cid):
    auth(["ProgramDirector"])
    c = _get(cid)
    if c["status"] not in ("FORMING", "AUDITIONING"):
        raise_err(ERR_INVALID_STATE, "cohort must be FORMING or AUDITIONING")
    from_forming = c["status"] == "FORMING"
    c["status"] = "DISSOLVED"
    stamp(c)
    for a in store.auditions.values():
        if a.get("cohort_program_id") != c["id"]:
            continue
        if from_forming:
            if a["outcome"] == "SCHEDULED":
                a["outcome"] = "REJECTED"
                stamp(a)
        else:
            if a["outcome"] not in ("SELECTED", "REJECTED"):
                a["outcome"] = "REJECTED"
                stamp(a)
    return success_obj(c)
