"""Mediation rounds: open, respond (accept/counter/decline), list."""
from datetime import timedelta

from flask import Blueprint

from auth import require_role, require_ownership
from errors import ApiError
from helpers import (
    body_json, req_str, req_enum, opt_str,
    get_case, get_round, ser_round, touch,
    apply_case_round_expiry, documentation_complete,
    ADDRESSED_TO, RESPONSES, RESPONSE_WINDOW_DAYS,
)
from routes_cases import _case_party_check
from store import db
from util import now, new_id, success, paginate

bp = Blueprint("rounds", __name__)


@bp.route("/reemployment/mediation-rounds", methods=["POST"])
def create_round():
    role, uid = require_role("Ombudsman")
    body = body_json()
    case_id = req_str(body, "case_id")
    proposal_text = req_str(body, "proposal_text")
    addressed_to = req_enum(body, "addressed_to", ADDRESSED_TO)
    case = get_case(case_id)
    # Only the assigned ombudsman opens rounds on the case.
    require_ownership(case["assigned_ombudsman_id"] == uid)
    apply_case_round_expiry(case)
    if case["status"] not in ("ASSIGNED", "IN_MEDIATION"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Case in %s cannot open a mediation round" % case["status"],
        )
    if any(r["case_id"] == case_id and r["status"] == "PROPOSED"
           for r in db.rounds.values()):
        raise ApiError(
            "ERR_ROUND_ALREADY_OPEN", 409,
            "The case already has a PROPOSED mediation round",
        )
    t = now()
    rid = new_id()
    round_number = 1 + sum(1 for r in db.rounds.values() if r["case_id"] == case_id)
    r = {
        "id": rid, "case_id": case_id, "round_number": round_number,
        "proposal_text": proposal_text, "addressed_to": addressed_to,
        "response_deadline": t + timedelta(days=RESPONSE_WINDOW_DAYS),
        "status": "PROPOSED", "response": None, "counter_text": None,
        "responded_at": None,
        "created_at": t, "updated_at": t, "version": 1, "_seq": db.next_seq(),
    }
    db.rounds[rid] = r
    case["status"] = "AWAITING_RESPONSE"
    touch(case)
    return success(ser_round(r), "object", 201)


@bp.route("/reemployment/mediation-rounds/<rid>/respond", methods=["POST"])
def respond_round(rid):
    role, uid = require_role("Employer", "ServiceMember")
    body = body_json()
    response = req_enum(body, "response", RESPONSES)
    counter_text = opt_str(body, "counter_text")
    if response == "COUNTER" and (counter_text is None or counter_text == ""):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "counter_text is required for a COUNTER response",
        )
    r = get_round(rid)
    case = get_case(r["case_id"])
    # Transition-level actor rule: the party named by addressed_to answers.
    if r["addressed_to"] == "EMPLOYER" and role != "Employer":
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            "This round is addressed to the employer",
        )
    if r["addressed_to"] == "MEMBER" and role != "ServiceMember":
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403,
            "This round is addressed to the member",
        )
    if role == "Employer":
        require_ownership(case["employer_id"] == uid)
    else:
        require_ownership(case["member_id"] == uid)
    t = now()
    # Lazy expiry on a respond attempt: past the deadline the round flips
    # EXPIRED, the case falls back to IN_MEDIATION, and the answer fails.
    # At exactly the deadline instant an answer is still timely.
    if r["status"] == "PROPOSED" and t > r["response_deadline"]:
        r["status"] = "EXPIRED"
        touch(r)
        if case["status"] == "AWAITING_RESPONSE":
            case["status"] = "IN_MEDIATION"
            touch(case)
        raise ApiError(
            "ERR_RESPONSE_DEADLINE_PASSED", 422,
            "The response deadline has passed",
        )
    if r["status"] != "PROPOSED":
        raise ApiError(
            "ERR_ROUND_NOT_OPEN", 409,
            "Round is already in terminal status %s" % r["status"],
        )
    if response == "ACCEPT":
        # Documentation gate: on failure the round stays PROPOSED and no
        # side effects fire.
        if not documentation_complete(case):
            raise ApiError(
                "ERR_DOCUMENTATION_INCOMPLETE", 409,
                "Case documentation standard is not met",
            )
        r["status"] = "ACCEPTED"
        r["response"] = "ACCEPT"
        r["responded_at"] = t
        touch(r)
        case["status"] = "RESOLVED_INFORMAL"
        case["closed_at"] = t
        touch(case)
    elif response == "COUNTER":
        r["status"] = "COUNTERED"
        r["response"] = "COUNTER"
        r["counter_text"] = counter_text
        r["responded_at"] = t
        touch(r)
        case["status"] = "IN_MEDIATION"
        touch(case)
    else:  # DECLINE
        r["status"] = "DECLINED"
        r["response"] = "DECLINE"
        r["responded_at"] = t
        touch(r)
        case["status"] = "IN_MEDIATION"
        touch(case)
    return success(ser_round(r))


@bp.route("/reemployment/cases/<cid>/rounds", methods=["GET"])
def list_rounds(cid):
    role, uid = require_role("ServiceMember", "Employer", "Ombudsman",
                             "ProgramCoordinator")
    case = get_case(cid)
    _case_party_check(case, role, uid)
    apply_case_round_expiry(case)
    items = [r for r in db.rounds.values() if r["case_id"] == cid]
    items.sort(key=lambda r: r["round_number"])
    page, meta = paginate(items)
    return success([ser_round(r) for r in page], "array", 200, meta)
