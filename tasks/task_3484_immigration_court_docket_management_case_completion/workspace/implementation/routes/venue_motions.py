# routes/venue_motions.py — change-of-venue motions: filing and the judge's
# ruling; a grant moves the case to the destination court and resets it to
# FILED for re-docketing (PRD §3.7).
import uuid

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_venue_motion
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_IMMIGRATION_JUDGE,
    CASE_FILED, CASE_COMPLETED, REQ_PENDING, REQ_GRANTED, REQ_DENIED,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, fk, pagination_params,
                    filter_param, sorted_page)
from scheduling import cancel_scheduled_hearings_of_case

bp = Blueprint("venue_motions", __name__)


def _load_motion(motion_id):
    m = db.venue_motions.get(motion_id)
    if m is None:
        raise ApiError("ERR_VENUE_MOTION_NOT_FOUND",
                       "ChangeOfVenueMotion id does not exist")
    return m


@bp.post("/venue-motions")
def create_motion():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    dest_id = fk(body, "destination_court_id")
    dest = db.courts.get(dest_id) if dest_id is not None else None
    if dest_id is not None and dest is None:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    if case is not None:
        # ---- tier 5: case terminality ----
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        # ---- tier 9: at most one PENDING venue motion per case ----
        if any(m for m in db.venue_motions.values()
               if m["case_id"] == case["id"] and m["status"] == REQ_PENDING):
            raise ApiError("ERR_VENUE_MOTION_ALREADY_PENDING",
                           "A PENDING change-of-venue motion already exists "
                           "for the case")
    # ---- tier 10: shape, then the semantic destination gate ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    dest_id = req_str(body, "destination_court_id")
    if dest_id not in db.courts:
        raise ApiError("ERR_COURT_NOT_FOUND", "Court id does not exist")
    reason = req_str(body, "reason")
    if dest_id == case["court_id"]:
        raise ApiError("ERR_DESTINATION_COURT_IS_CURRENT",
                       "Destination court equals the case's current court")
    m = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "destination_court_id": dest_id,
        "reason": reason,
        "status": REQ_PENDING,
        "decided_by_judge_id": None,
        "decided_at": None,
    }
    db.stamp_new(m)
    db.stamp_common(m)
    db.venue_motions[m["id"]] = m
    return success(serialize_venue_motion(m), response_type="object",
                   status=201)


@bp.get("/venue-motions")
def list_motions():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.venue_motions.values())
    for name in ("case_id", "destination_court_id", "status",
                 "decided_by_judge_id"):
        v = filter_param(name)
        if v is not None:
            records = [m for m in records if m.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_venue_motion(m) for m in page], total,
                         limit, offset)


@bp.get("/venue-motions/<motionId>")
def get_motion(motionId):
    get_auth()  # all roles
    return success(serialize_venue_motion(_load_motion(motionId)),
                   response_type="object", status=200)


@bp.post("/venue-motions/<motionId>/decide")
def decide_motion(motionId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    # tier 3
    m = _load_motion(motionId)
    case = db.cases[m["case_id"]]
    # tier 4: ownership binds to the case's assigned judge
    if case["assigned_judge_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_JUDGE",
                       "X-User-ID must equal the case's assigned_judge_id")
    # tier 5: the motion's own posture first, then case terminality
    if m["status"] != REQ_PENDING:
        raise ApiError("ERR_VENUE_MOTION_NOT_PENDING",
                       "Venue motion is not PENDING")
    if case["status"] == CASE_COMPLETED:
        raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                       "Case has reached COMPLETED")
    # tier 10: shape
    body = get_body()
    ruling = req_enum(body, "decision", (REQ_GRANTED, REQ_DENIED))
    # ---- commit ----
    m["status"] = ruling
    m["decided_by_judge_id"] = user_id
    m["decided_at"] = db.get_clock()
    db.touch(m)
    if ruling == REQ_GRANTED:
        # venue change resets the case so the new court re-dockets it
        case["court_id"] = m["destination_court_id"]
        case["assigned_judge_id"] = None
        case["status"] = CASE_FILED
        cancel_scheduled_hearings_of_case(case["id"])
        db.touch(case)  # increments Case.version by 1
    # DENIED ends the matter
    return success(serialize_venue_motion(m), response_type="object",
                   status=200)
