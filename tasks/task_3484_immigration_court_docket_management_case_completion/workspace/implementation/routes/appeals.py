# routes/appeals.py — appeal filing with the review board and board rulings
# (affirm / remand / dismiss), including the remand auto-hearing (PRD §3.6).
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from auth import get_auth, require_role
from computed import serialize_appeal
from constants import (
    ROLE_COURT_ADMINISTRATOR, ROLE_BOARD_MEMBER,
    CASE_DECIDED, CASE_IN_ABSENTIA, CASE_APPEALED, CASE_MERITS,
    CASE_COMPLETED,
    DEC_ISSUED, DEC_APPEAL_PENDING, DEC_FINAL, DEC_REMANDED,
    APPEAL_FILED, APPEAL_AFFIRMED, APPEAL_REMANDED, APPEAL_DISMISSED,
    APPEAL_RULINGS, HEARING_MERITS, AUTO_HEARING_REMAND_DAYS,
)
from envelope import success, list_response
from errors import ApiError
from inputs import (get_body, req_str, req_enum, opt_str, fk,
                    pagination_params, filter_param, sorted_page)
from scheduling import auto_schedule_hearing

bp = Blueprint("appeals", __name__)


def _load_appeal(appeal_id):
    a = db.appeals.get(appeal_id)
    if a is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND", "Appeal id does not exist")
    return a


@bp.post("/appeals")
def create_appeal():
    _, role = get_auth()
    require_role(role, (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    # ---- tier 3: body FKs in declared input order (decision_id) ----
    decision_id = fk(body, "decision_id")
    decision = db.decisions.get(decision_id) if decision_id is not None else None
    if decision_id is not None and decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND", "Decision id does not exist")
    if decision is not None:
        # ---- tier 5: the decision must still be ISSUED ----
        if decision["status"] != DEC_ISSUED:
            raise ApiError("ERR_DECISION_NOT_APPEALABLE",
                           "Only an ISSUED decision can be appealed")
        # ---- tier 8: the 30-day window is INCLUSIVE of the deadline ----
        if db.get_clock() > decision["appeal_deadline"]:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED",
                           "Clock is strictly past the decision's "
                           "appeal_deadline")
    # ---- tier 10: shape ----
    decision_id = req_str(body, "decision_id")
    decision = db.decisions.get(decision_id)
    if decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND", "Decision id does not exist")
    grounds = opt_str(body, "grounds")
    # ---- commit ----
    clock = db.get_clock()
    case = db.cases[decision["case_id"]]
    appeal = {
        "id": str(uuid.uuid4()),
        "decision_id": decision["id"],
        "case_id": case["id"],
        "grounds": grounds,
        "filed_at": clock,
        "status": APPEAL_FILED,
        "remand_instructions": None,
        "decided_by_board_member_id": None,
        "decided_at": None,
    }
    db.stamp_new(appeal)
    db.stamp_common(appeal)
    db.appeals[appeal["id"]] = appeal
    decision["status"] = DEC_APPEAL_PENDING
    db.touch(decision)
    # both decided postures (DECIDED and IN_ABSENTIA) move to APPEALED
    if case["status"] in (CASE_DECIDED, CASE_IN_ABSENTIA):
        case["status"] = CASE_APPEALED
    db.touch(case)  # increments Case.version by 1
    return success(serialize_appeal(appeal), response_type="object",
                   status=201)


@bp.get("/appeals")
def list_appeals():
    get_auth()  # all roles
    limit, offset = pagination_params()
    records = list(db.appeals.values())
    for name in ("decision_id", "case_id", "status"):
        v = filter_param(name)
        if v is not None:
            records = [a for a in records if a.get(name) == v]
    page, total = sorted_page(records, limit, offset)
    return list_response([serialize_appeal(a) for a in page], total, limit,
                         offset)


@bp.get("/appeals/<appealId>")
def get_appeal(appealId):
    get_auth()  # all roles
    return success(serialize_appeal(_load_appeal(appealId)),
                   response_type="object", status=200)


@bp.post("/appeals/<appealId>/decide")
def decide_appeal(appealId):
    user_id, role = get_auth()
    require_role(role, (ROLE_BOARD_MEMBER,))
    # tier 3
    appeal = _load_appeal(appealId)
    # (BoardMember identity is opaque: no tier-4 entity binding)
    # tier 5: the appeal must still be FILED
    if appeal["status"] != APPEAL_FILED:
        raise ApiError("ERR_APPEAL_ALREADY_DECIDED",
                       "Appeal is not in FILED status")
    # tier 10: shape, then the REMANDED instructions gate
    body = get_body()
    ruling = req_enum(body, "ruling", APPEAL_RULINGS)
    remand_instructions = opt_str(body, "remand_instructions")
    if ruling == APPEAL_REMANDED and remand_instructions is None:
        raise ApiError("ERR_REMAND_INSTRUCTIONS_REQUIRED",
                       "A REMANDED ruling requires remand_instructions")
    # ---- commit ----
    clock = db.get_clock()
    decision = db.decisions[appeal["decision_id"]]
    case = db.cases[appeal["case_id"]]
    appeal["status"] = ruling
    appeal["decided_by_board_member_id"] = user_id
    appeal["decided_at"] = clock
    if ruling in (APPEAL_AFFIRMED, APPEAL_DISMISSED):
        # symmetrical endings: decision FINAL, case COMPLETED
        decision["status"] = DEC_FINAL
        db.touch(decision)
        case["status"] = CASE_COMPLETED
        case["completed_at"] = clock
        db.touch(case)  # increments Case.version by 1
    else:  # REMANDED reopens the merits phase
        appeal["remand_instructions"] = remand_instructions
        decision["status"] = DEC_REMANDED
        db.touch(decision)
        case["status"] = CASE_MERITS
        db.touch(case)  # increments Case.version by 1
        auto_schedule_hearing(
            case, HEARING_MERITS,
            clock + timedelta(days=AUTO_HEARING_REMAND_DAYS),
            False,  # is_remote not specified for auto remand hearings
            supersedes_hearing_id=None,
            judge_id=case["assigned_judge_id"])
    db.touch(appeal)
    return success(serialize_appeal(appeal), response_type="object",
                   status=200)
