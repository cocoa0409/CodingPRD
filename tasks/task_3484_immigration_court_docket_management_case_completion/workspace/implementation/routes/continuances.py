# routes/continuances.py — continuance requests: filing gates (lead time,
# caps, first-request carve-out) and the judge's ruling with its cascades.
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_continuance, case_continuance_count
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_IMMIGRATION_JUDGE,
    CASE_COMPLETED, CASE_CALENDAR, CASE_MERITS, CASE_ADMIN_CLOSED,
    CUSTODY_DETAINED,
    CONTINUANCE_REASONS, REASON_ATTORNEY, REASON_PENDING_APPLICATION,
    REQ_PENDING, REQ_GRANTED, REQ_DENIED,
    HEARING_SCHEDULED, HEARING_CONTINUED, HEARING_CANCELLED,
    CONTINUANCE_CAP_DETAINED, CONTINUANCE_CAP_NON_DETAINED,
    CONTINUANCE_LEAD_HOURS, CONTINUANCE_BUMP_DAYS_DETAINED,
    CONTINUANCE_BUMP_DAYS_NON_DETAINED,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, fk, pagination_params,
                    filter_param, sorted_page)
from scheduling import auto_schedule_hearing

bp = Blueprint("continuances", __name__)


def _load_request(request_id):
    r = db.continuances.get(request_id)
    if r is None:
        raise ApiError("ERR_CONTINUANCE_NOT_FOUND",
                       "ContinuanceRequest id does not exist")
    return r


@bp.post("/continuance-requests")
def create_continuance():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (case_id, hearing_id) ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    hearing_id = fk(body, "hearing_id")
    hearing = db.hearings.get(hearing_id) if hearing_id is not None else None
    if hearing_id is not None and hearing is None:
        raise ApiError("ERR_HEARING_NOT_FOUND", "Hearing id does not exist")
    reason = fk(body, "reason_code")

    if case is not None and hearing is not None:
        # ---- tier 5: case terminality ----
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        # ---- tier 6: the targeted hearing must belong to the named case ----
        if hearing["case_id"] != case["id"]:
            raise ApiError("ERR_HEARING_CASE_MISMATCH",
                           "hearing_id belongs to a different case")
        # ---- tier 8: 24h lead time; the case's first-ever
        # ATTORNEY_REPRESENTATION request is exempt (PRD §3.4) ----
        is_first = not any(r for r in db.continuances.values()
                           if r["case_id"] == case["id"])
        carve_out = is_first and reason == REASON_ATTORNEY
        if not carve_out and db.get_clock() > hearing["scheduled_start"] \
                - timedelta(hours=CONTINUANCE_LEAD_HOURS):
            raise ApiError("ERR_CONTINUANCE_TOO_LATE",
                           "Continuance must be filed no later than 24 hours "
                           "before the hearing start")
        # ---- tier 9: one PENDING continuance per hearing; then the caps ----
        if any(r for r in db.continuances.values()
               if r["hearing_id"] == hearing["id"]
               and r["status"] == REQ_PENDING):
            raise ApiError("ERR_CONTINUANCE_ALREADY_PENDING",
                           "A PENDING continuance already targets this "
                           "hearing")
        cap = CONTINUANCE_CAP_DETAINED if case["custody_status"] == CUSTODY_DETAINED \
            else CONTINUANCE_CAP_NON_DETAINED
        if case_continuance_count(case["id"]) >= cap:
            raise ApiError("ERR_CONTINUANCE_CAP_REACHED",
                           "The case's granted-continuance count is already "
                           "at its cap")

    # ---- tier 10: shape, then the semantic representation gate ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    hearing_id = req_str(body, "hearing_id")
    hearing = db.hearings.get(hearing_id)
    if hearing is None:
        raise ApiError("ERR_HEARING_NOT_FOUND", "Hearing id does not exist")
    reason = req_enum(body, "reason_code", CONTINUANCE_REASONS)
    if reason == REASON_ATTORNEY and case["representation_status"] != "PRO_SE":
        raise ApiError("ERR_REASON_REQUIRES_PRO_SE",
                       "ATTORNEY_REPRESENTATION continuances require a "
                       "PRO_SE case")
    is_first = not any(r for r in db.continuances.values()
                       if r["case_id"] == case["id"])
    r = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "hearing_id": hearing["id"],
        "reason_code": reason,
        "is_first_for_case": is_first,
        "status": REQ_PENDING,
        "decided_by_judge_id": None,
        "decided_at": None,
    }
    db.stamp_new(r)
    db.stamp_common(r)
    db.continuances[r["id"]] = r
    return success(serialize_continuance(r), response_type="object",
                   status=201)


@bp.get("/continuance-requests")
def list_continuances():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.continuances.values())
    for name in ("case_id", "hearing_id", "status", "decided_by_judge_id"):
        v = filter_param(name)
        if v is not None:
            records = [r for r in records if r.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_continuance(r) for r in page], total,
                         limit, offset)


@bp.get("/continuance-requests/<requestId>")
def get_continuance(requestId):
    get_auth()  # all roles
    return success(serialize_continuance(_load_request(requestId)),
                   response_type="object", status=200)


@bp.post("/continuance-requests/<requestId>/decide")
def decide_continuance(requestId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    # tier 3
    r = _load_request(requestId)
    case = db.cases[r["case_id"]]
    hearing = db.hearings.get(r["hearing_id"])
    # tier 4: ownership binds to the case's assigned judge
    if case["assigned_judge_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_JUDGE",
                       "X-User-ID must equal the case's assigned_judge_id")
    # tier 5: the acting entity's own posture first, then case terminality
    if r["status"] != REQ_PENDING:
        raise ApiError("ERR_CONTINUANCE_NOT_PENDING",
                       "Continuance request is not PENDING")
    if case["status"] == CASE_COMPLETED:
        raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                       "Case has reached COMPLETED")
    # tier 10: shape
    body = get_body()
    ruling = req_enum(body, "decision", (REQ_GRANTED, REQ_DENIED))
    # ---- commit ----
    r["status"] = ruling
    r["decided_by_judge_id"] = user_id
    r["decided_at"] = db.get_clock()
    db.touch(r)
    if ruling == REQ_GRANTED:
        if r["reason_code"] == REASON_PENDING_APPLICATION:
            # respondent pursues an application elsewhere: cancel the hearing,
            # no replacement, and the case administratively closes
            if hearing is not None and hearing["status"] == HEARING_SCHEDULED:
                hearing["status"] = HEARING_CANCELLED
                db.touch(hearing)
            if case["status"] in (CASE_CALENDAR, CASE_MERITS):
                case["status"] = CASE_ADMIN_CLOSED
            db.touch(case)  # increments Case.version by 1
        else:
            # hearing -> CONTINUED and the system auto-creates its replacement
            if hearing is not None and hearing["status"] == HEARING_SCHEDULED:
                hearing["status"] = HEARING_CONTINUED
                db.touch(hearing)
                bump = CONTINUANCE_BUMP_DAYS_DETAINED \
                    if case["custody_status"] == CUSTODY_DETAINED \
                    else CONTINUANCE_BUMP_DAYS_NON_DETAINED
                auto_schedule_hearing(
                    case, hearing["hearing_type"],
                    hearing["scheduled_start"] + timedelta(days=bump),
                    hearing["is_remote"],
                    supersedes_hearing_id=hearing["id"],
                    judge_id=hearing["judge_id"])
            db.touch(case)  # increments Case.version by 1
    # DENIED touches nothing else — the targeted hearing stands
    return success(serialize_continuance(r), response_type="object",
                   status=200)
