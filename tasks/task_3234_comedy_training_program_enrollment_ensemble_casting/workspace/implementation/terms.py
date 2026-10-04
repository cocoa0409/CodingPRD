"""Term routes and cascade transitions."""
from flask import Blueprint
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_SECTION_UNSTAFFED
from services import recompute_section_counts, cancel_section_cascade, credit_enrollment

bp = Blueprint("terms", __name__)

ROLES_READ = ["ProgramDirector", "Registrar", "CastingDirector", "Student", "FinanceOfficer", "PlacementOfficer"]


def _get_term(termId):
    term = store.terms.get(termId)
    if not term:
        not_found("term not found")
    return term


@bp.post("/terms")
def create_term():
    auth(["ProgramDirector"])
    body = json_body()
    require_fields(body, ["name", "start_utc", "end_utc", "drop_deadline_utc"])
    term = fresh({
        "name": body["name"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "drop_deadline_utc": body["drop_deadline_utc"],
        "status": "DRAFT",
    })
    store.terms[term["id"]] = term
    return success_obj(term, 201)


@bp.get("/terms")
def list_terms():
    auth(ROLES_READ)
    limit, offset = pagination_params()
    items = sorted(store.terms.values(), key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/terms/<termId>")
def get_term(termId):
    auth(ROLES_READ)
    return success_obj(_get_term(termId))


def _transition(term, expected, target):
    if term["status"] != expected:
        raise_err(ERR_INVALID_STATE, f"term must be {expected}")
    term["status"] = target
    stamp(term)


@bp.post("/terms/<termId>/open-scheduling")
def open_scheduling(termId):
    auth(["ProgramDirector"])
    term = _get_term(termId)
    _transition(term, "DRAFT", "SCHEDULING")
    return success_obj(term)


@bp.post("/terms/<termId>/open-enrollment")
def open_enrollment(termId):
    auth(["ProgramDirector"])
    term = _get_term(termId)
    if term["status"] != "SCHEDULING":
        raise_err(ERR_INVALID_STATE, "term must be SCHEDULING")
    # staffing audit: every non-CANCELLED section must have an instructor
    for sec in store.sections.values():
        if sec["term_id"] == term["id"] and sec["status"] != "CANCELLED":
            if not sec.get("instructor_id"):
                raise_err(ERR_SECTION_UNSTAFFED, "a non-cancelled section has no instructor")
    term["status"] = "ENROLLMENT_OPEN"
    stamp(term)
    for sec in store.sections.values():
        if sec["term_id"] == term["id"] and sec["status"] == "DRAFT":
            sec["status"] = "OPEN"
            stamp(sec)
    return success_obj(term)


@bp.post("/terms/<termId>/start-session")
def start_session(termId):
    auth(["ProgramDirector"])
    term = _get_term(termId)
    if term["status"] != "ENROLLMENT_OPEN":
        raise_err(ERR_INVALID_STATE, "term must be ENROLLMENT_OPEN")
    term["status"] = "IN_SESSION"
    stamp(term)
    for sec in store.sections.values():
        if sec["term_id"] != term["id"]:
            continue
        recompute_section_counts(sec)
        if sec["status"] == "OPEN":
            if sec["enrolled_count"] >= 1:
                sec["status"] = "LOCKED"
                stamp(sec)
            else:
                sec["status"] = "CANCELLED"
                stamp(sec)
                cancel_section_cascade(sec)
    # second pass: LOCKED sections at capacity -> RUNNING
    for sec in store.sections.values():
        if sec["term_id"] == term["id"] and sec["status"] == "LOCKED":
            recompute_section_counts(sec)
            if sec["enrolled_count"] >= sec["capacity"]:
                sec["status"] = "RUNNING"
                stamp(sec)
    # cohort cascade: CASTED -> ACTIVE for cohorts in this term
    for cohort in store.cohorts.values():
        if cohort["term_id"] == term["id"] and cohort["status"] == "CASTED":
            cohort["status"] = "ACTIVE"
            stamp(cohort)
    return success_obj(term)


@bp.post("/terms/<termId>/close")
def close_term(termId):
    auth(["ProgramDirector"])
    term = _get_term(termId)
    if term["status"] != "IN_SESSION":
        raise_err(ERR_INVALID_STATE, "term must be IN_SESSION")
    term["status"] = "CLOSED"
    stamp(term)
    for sec in list(store.sections.values()):
        if sec["term_id"] != term["id"] or sec["status"] != "RUNNING":
            continue
        sec["status"] = "COMPLETED"
        stamp(sec)
        completed_enrollments = []
        for e in store.enrollments.values():
            if e["section_id"] == sec["id"] and e["status"] == "CONFIRMED":
                e["status"] = "COMPLETED"
                stamp(e)
                completed_enrollments.append(e)
        level = store.levels.get(sec["level_id"])
        if level and level.get("showcase_required") and completed_enrollments:
            showcase = fresh({
                "level_id": level["id"],
                "venue_slot_id": None,
                "term_id": term["id"],
                "is_industry": False,
                "performer_enrollment_ids": [e["id"] for e in completed_enrollments],
                "grade_by_enrollment": {},
                "status": "PLANNED",
            })
            store.showcases[showcase["id"]] = showcase
        elif level and not level.get("showcase_required"):
            # credit directly when showcase not required
            for e in completed_enrollments:
                credit_enrollment(e)
    return success_obj(term)
