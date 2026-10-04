# routes/decisions.py — judge-issued decisions on MERITS cases (PRD §3.6).
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_decision
from constants import (
    ROLE_IMMIGRATION_JUDGE, CASE_MERITS, CASE_DECIDED, CASE_COMPLETED,
    HEARING_MERITS, HEARING_COMPLETED,
    DECISION_OUTCOMES, OUTCOME_IN_ABSENTIA, DEC_ISSUED, APPEAL_WINDOW_DAYS,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, req_version, fk,
                    pagination_params, filter_param, sorted_page)

bp = Blueprint("decisions", __name__)


@bp.post("/decisions")
def create_decision():
    user_id, role = get_auth()
    require_role(role, (ROLE_IMMIGRATION_JUDGE,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (case_id) ----
    case_id = fk(body, "case_id")
    case = db.cases.get(case_id) if case_id is not None else None
    if case_id is not None and case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    if case is not None:
        # ---- tier 4: ownership binds to the case's assigned judge ----
        if case["assigned_judge_id"] != user_id:
            raise ApiError("ERR_NOT_ASSIGNED_JUDGE",
                           "X-User-ID must equal the case's assigned_judge_id")
        # ---- tier 5: terminality, then the case's own phase BEFORE the
        # completed-merits-hearing prerequisite (PRD §2.6 tier-5 intra-order)
        if case["status"] == CASE_COMPLETED:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL",
                           "Case has reached COMPLETED")
        if case["status"] != CASE_MERITS:
            raise ApiError("ERR_CASE_NOT_IN_MERITS",
                           "Decision issuance requires the case to be MERITS")
        if not any(h for h in db.hearings.values()
                   if h["case_id"] == case["id"]
                   and h["hearing_type"] == HEARING_MERITS
                   and h["status"] == HEARING_COMPLETED):
            raise ApiError("ERR_NO_COMPLETED_MERITS_HEARING",
                           "No COMPLETED INDIVIDUAL_MERITS hearing exists "
                           "for the case")
    # ---- tier 10: shape, then the system-only outcome gate ----
    case_id = req_str(body, "case_id")
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", "Case id does not exist")
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)
    expected_version = req_version(body, "expected_case_version")
    if outcome == OUTCOME_IN_ABSENTIA:
        raise ApiError("ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE",
                       "IN_ABSENTIA_REMOVAL is system-only and enters via "
                       "the no-show cascade")
    # ---- tier 11: OCC, immediately before commit ----
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION",
                       "expected_case_version does not equal the case's "
                       "current version")
    # ---- commit ----
    clock = db.get_clock()
    decision = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "judge_id": user_id,
        "outcome": outcome,
        "source_hearing_id": None,  # null for judge-issued decisions
        "issued_at": clock,
        "appeal_deadline": clock + timedelta(days=APPEAL_WINDOW_DAYS),
        "reopen_deadline": None,    # only IN_ABSENTIA_REMOVAL carries one
        "status": DEC_ISSUED,
    }
    db.stamp_new(decision)
    db.stamp_common(decision)
    db.decisions[decision["id"]] = decision
    case["status"] = CASE_DECIDED
    db.touch(case)  # increments Case.version by 1
    return success(serialize_decision(decision), response_type="object",
                   status=201)


@bp.get("/decisions")
def list_decisions():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.decisions.values())
    for name in ("case_id", "judge_id", "source_hearing_id", "status"):
        v = filter_param(name)
        if v is not None:
            records = [d for d in records if d.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_decision(d) for d in page], total, limit,
                         offset)


@bp.get("/decisions/<decisionId>")
def get_decision(decisionId):
    get_auth()  # all roles
    d = db.decisions.get(decisionId)
    if d is None:
        raise ApiError("ERR_DECISION_NOT_FOUND", "Decision id does not exist")
    return success(serialize_decision(d), response_type="object", status=200)
