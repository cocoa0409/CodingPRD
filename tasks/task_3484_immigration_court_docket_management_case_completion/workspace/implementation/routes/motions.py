# routes/motions.py — motions to reopen in absentia orders (PRD §3.5),
# including the second-entity rescindability check that runs immediately
# after the tier-6 linkage check (PRD §2.6).
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_motion
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_IMMIGRATION_JUDGE,
    CASE_IN_ABSENTIA, CASE_CALENDAR, CASE_COMPLETED,
    MOTION_FILED, MOTION_GRANTED, MOTION_DENIED, MOTION_BASES,
    BASIS_NOTICE_DEFECTIVE, BASIS_EXCEPTIONAL,
    DEC_ISSUED, DEC_RESCINDED, OUTCOME_IN_ABSENTIA,
    NOTICE_DEFECTIVE, HEARING_MASTER, AUTO_HEARING_REOPEN_DAYS,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, fk, pagination_params,
                    filter_param, sorted_page)
from scheduling import auto_schedule_hearing

bp = Blueprint("motions", __name__)


def _load_motion(motion_id):
    m = db.motions.get(motion_id)
    if m is None:
        raise ApiError("ERR_MOTION_NOT_FOUND",
                       "MotionToReopen id does not exist")
    return m


@bp.post("/motions-to-reopen")
def create_motion():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (case_id, decision_id) ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    decision_id = fk(body, "decision_id")
    decision = db.decisions.get(decision_id) if decision_id is not None else None
    if decision_id is not None and decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND", "Decision id does not exist")
    basis = fk(body, "basis")

    if case is not None and decision is not None:
        # ---- tier 5: the acting entity's own phase (case IN_ABSENTIA) ----
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        if case["status"] != CASE_IN_ABSENTIA:
            raise ApiError("ERR_CASE_NOT_IN_ABSENTIA",
                           "A motion to reopen requires the case to be "
                           "IN_ABSENTIA")
        # ---- tier 6: linkage — the decision must belong to the case ----
        if decision["case_id"] != case["id"]:
            raise ApiError("ERR_DECISION_CASE_MISMATCH",
                           "decision_id belongs to a different case")
        # ---- second-entity state check, immediately after tier 6 ----
        if decision["status"] != DEC_ISSUED \
                or decision["outcome"] != OUTCOME_IN_ABSENTIA:
            raise ApiError("ERR_DECISION_NOT_RESCINDABLE",
                           "The target decision is not a still-ISSUED "
                           "IN_ABSENTIA_REMOVAL order")
        # ---- tier 7: NOTICE_DEFECTIVE requires the source hearing's notice
        # to be DEFECTIVE (skip when basis is not yet known-valid) ----
        if basis == BASIS_NOTICE_DEFECTIVE:
            source = db.hearings.get(decision.get("source_hearing_id") or "")
            notice = None
            if source is not None:
                notice = next((n for n in db.notices.values()
                               if n["hearing_id"] == source["id"]), None)
            if notice is None or notice["status"] != NOTICE_DEFECTIVE:
                raise ApiError("ERR_NOTICE_NOT_DEFECTIVE",
                               "A NOTICE_DEFECTIVE motion requires the source "
                               "hearing's notice to be DEFECTIVE")
        # ---- tier 8: EXCEPTIONAL_CIRCUMSTANCES is window-bound (inclusive);
        # NOTICE_DEFECTIVE is exempt from the window entirely ----
        if basis == BASIS_EXCEPTIONAL:
            if db.get_clock() > decision["reopen_deadline"]:
                raise ApiError("ERR_REOPEN_WINDOW_EXPIRED",
                               "Clock is strictly past the decision's "
                               "reopen_deadline")
        # ---- tier 9: at most one FILED motion to reopen per case ----
        if any(m for m in db.motions.values()
               if m["case_id"] == case["id"] and m["status"] == MOTION_FILED):
            raise ApiError("ERR_MOTION_ALREADY_PENDING",
                           "A FILED motion to reopen already exists for the "
                           "case")

    # ---- tier 10: shape ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    decision_id = req_str(body, "decision_id")
    if decision_id not in db.decisions:
        raise ApiError("ERR_DECISION_NOT_FOUND", "Decision id does not exist")
    basis = req_enum(body, "basis", MOTION_BASES)
    m = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "decision_id": decision_id,
        "basis": basis,
        "filed_at": db.get_clock(),
        "status": MOTION_FILED,
        "decided_by_judge_id": None,
        "decided_at": None,
    }
    db.stamp_new(m)
    db.stamp_common(m)
    db.motions[m["id"]] = m
    return success(serialize_motion(m), response_type="object", status=201)


@bp.get("/motions-to-reopen")
def list_motions():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.motions.values())
    for name in ("case_id", "decision_id", "status", "decided_by_judge_id"):
        v = filter_param(name)
        if v is not None:
            records = [m for m in records if m.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_motion(m) for m in page], total, limit,
                         offset)


@bp.get("/motions-to-reopen/<motionId>")
def get_motion(motionId):
    get_auth()  # all roles
    return success(serialize_motion(_load_motion(motionId)),
                   response_type="object", status=200)


@bp.post("/motions-to-reopen/<motionId>/decide")
def decide_motion(motionId):
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    # tier 3
    m = _load_motion(motionId)
    case = db.cases[m["case_id"]]
    # tier 4: ownership binds to the case's (retained) assigned judge
    if case["assigned_judge_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_JUDGE",
                       "X-User-ID must equal the case's assigned_judge_id")
    # tier 5: the motion's own posture first, then case terminality
    if m["status"] != MOTION_FILED:
        raise ApiError("ERR_MOTION_NOT_PENDING",
                       "Motion to reopen is not in FILED status")
    if case["status"] == CASE_COMPLETED:
        raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                       "Case has reached COMPLETED")
    # tier 10: shape
    body = get_body()
    ruling = req_enum(body, "decision", (MOTION_GRANTED, MOTION_DENIED))
    # ---- commit ----
    clock = db.get_clock()
    m["status"] = ruling
    m["decided_by_judge_id"] = user_id
    m["decided_at"] = clock
    db.touch(m)
    if ruling == MOTION_GRANTED:
        # unwind the removal: decision RESCINDED, case back to CALENDAR,
        # system auto-creates a fresh master-calendar hearing 21 days out
        decision = db.decisions.get(m["decision_id"])
        if decision is not None:
            decision["status"] = DEC_RESCINDED
            db.touch(decision)
        if case["status"] == CASE_IN_ABSENTIA:
            case["status"] = CASE_CALENDAR
        db.touch(case)  # increments Case.version by 1
        auto_schedule_hearing(
            case, HEARING_MASTER,
            clock + timedelta(days=AUTO_HEARING_REOPEN_DAYS),
            False,  # is_remote not specified for auto reopen hearings
            supersedes_hearing_id=None,
            judge_id=case["assigned_judge_id"])
    # DENIED leaves the decision and the case untouched
    return success(serialize_motion(m), response_type="object", status=200)
