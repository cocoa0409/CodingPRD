# routes/cases.py — case initiation (charging-document filing), docketing,
# administrative closure, and recalendar.
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_case, judge_pending_load
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_IMMIGRATION_JUDGE,
    CASE_FILED, CASE_CALENDAR, CASE_MERITS, CASE_ADMIN_CLOSED, CASE_COMPLETED,
    CUSTODY_STATUSES, REPRESENTATION_STATUSES,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, req_lang, opt_bool, fk,
                    pagination_params, filter_param, sorted_page)
from scheduling import cancel_scheduled_hearings_of_case

bp = Blueprint("cases", __name__)


def _load_case(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    return case


def _check_not_terminal(case):
    # Any mutation against a COMPLETED case is rejected outright (PRD §3.2);
    # checked at the head of tier 5 before the operation-specific phase gate.
    if case["status"] == CASE_COMPLETED:
        raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                       "Case has reached COMPLETED and admits no further "
                       "mutation")


def _check_owning_judge(user_id, case):
    # Tier 4 ownership binding (ERR_NOT_ASSIGNED_JUDGE, 403)
    if case["assigned_judge_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_JUDGE",
                       "X-User-ID must equal the case's assigned_judge_id")


@bp.post("/cases")
def create_case():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # tier 3: body FKs in declared input order (court_id first)
    court_id = fk(body, "court_id")
    if court_id is not None and court_id not in db.courts:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    # tier 9: case_number unique within the venue court
    case_number = fk(body, "case_number")
    if court_id is not None and case_number is not None and any(
            c["court_id"] == court_id and c["case_number"] == case_number
            for c in db.cases.values()):
        raise ApiError("ERR_CASE_NUMBER_NOT_UNIQUE",
                       "case_number already exists within the venue court")
    # tier 10: shape
    court_id = req_str(body, "court_id")
    if court_id not in db.courts:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    case_number = req_str(body, "case_number")
    respondent = req_str(body, "respondent_full_name")
    custody = req_enum(body, "custody_status", CUSTODY_STATUSES)
    language = req_lang(body, "primary_language_code")
    representation = req_enum(body, "representation_status",
                              REPRESENTATION_STATUSES)
    interpreter_required = opt_bool(body, "interpreter_required", default=True)
    case = {
        "id": str(uuid.uuid4()),
        "court_id": court_id,
        "case_number": case_number,
        "respondent_full_name": respondent,
        "custody_status": custody,
        "primary_language_code": language,
        "representation_status": representation,
        "interpreter_required": interpreter_required,
        "assigned_judge_id": None,
        "status": CASE_FILED,
        "filed_at": db.get_clock(),
        "completed_at": None,
    }
    db.stamp_new(case)
    db.stamp_common(case)
    db.cases[case["id"]] = case
    # venue court's pending_case_count / is_backlog_critical recompute live
    return success(serialize_case(case), response_type="object", status=201)


@bp.get("/cases")
def list_cases():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.cases.values())
    for name in ("court_id", "assigned_judge_id", "status", "custody_status"):
        v = filter_param(name)
        if v is not None:
            records = [c for c in records if c.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_case(c) for c in page], total, limit,
                         offset)


@bp.get("/cases/<caseId>")
def get_case(caseId):
    get_auth()  # all roles
    return success(serialize_case(_load_case(caseId)),
                   response_type="object", status=200)


@bp.post("/cases/<caseId>/assign-judge")
def assign_judge(caseId):
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    # tier 3: path id first, then body FKs in declared input order
    case = _load_case(caseId)
    body = get_body()
    judge_id = fk(body, "judge_id")
    judge = db.judges.get(judge_id) if judge_id is not None else None
    if judge_id is not None and judge is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", "Judge id does not exist")
    # tier 5: terminality, then the acting entity's own phase
    _check_not_terminal(case)
    if case["status"] != CASE_FILED:
        raise ApiError("ERR_CASE_NOT_AWAITING_DOCKET",
                       "assign-judge requires the case to be FILED")
    # tier 6: judge must sit at the case's venue court
    if judge is not None and judge["court_id"] != case["court_id"]:
        raise ApiError("ERR_JUDGE_WRONG_COURT",
                       "Judge's home court differs from the case's venue")
    # tier 9: caseload cap (load strictly below max; equal rejects)
    if judge is not None \
            and judge_pending_load(judge["id"]) >= judge["max_pending_cases"]:
        raise ApiError("ERR_JUDGE_CASELOAD_FULL",
                       "Judge's pending_case_load has reached "
                       "max_pending_cases")
    # tier 10: shape
    judge_id = req_str(body, "judge_id")
    judge = db.judges.get(judge_id)
    if judge is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", "Judge id does not exist")
    # commit
    case["assigned_judge_id"] = judge_id
    case["status"] = CASE_CALENDAR
    db.touch(case)  # increments Case.version by 1
    return success(serialize_case(case), response_type="object", status=200)


@bp.post("/cases/<caseId>/administrative-closure")
def administrative_closure(caseId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    case = _load_case(caseId)
    body = get_body()
    # tier 4: ownership
    _check_owning_judge(user_id, case)
    # tier 5: terminality, then phase
    _check_not_terminal(case)
    if case["status"] not in (CASE_CALENDAR, CASE_MERITS):
        raise ApiError("ERR_CASE_STATE_FORBIDS_CLOSURE",
                       "administrative-closure requires CALENDAR or MERITS")
    # tier 10: shape
    closure_reason = req_str(body, "closure_reason")
    case["closure_reason"] = closure_reason
    # conditional cascade: only SCHEDULED hearings are cancelled
    cancel_scheduled_hearings_of_case(case["id"])
    case["status"] = CASE_ADMIN_CLOSED
    db.touch(case)
    return success(serialize_case(case), response_type="object", status=200)


@bp.post("/cases/<caseId>/recalendar")
def recalendar(caseId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    case = _load_case(caseId)
    get_body()  # no declared input
    # tier 4: ownership
    _check_owning_judge(user_id, case)
    # tier 5: terminality, then phase
    _check_not_terminal(case)
    if case["status"] != CASE_ADMIN_CLOSED:
        raise ApiError("ERR_CASE_NOT_ADMIN_CLOSED",
                       "recalendar requires the case to be ADMIN_CLOSED")
    case["status"] = CASE_MERITS
    db.touch(case)
    return success(serialize_case(case), response_type="object", status=200)
