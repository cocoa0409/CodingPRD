"""State correspondence: notices, response rounds, appeals and assessments."""
from flask import Blueprint

from calc import (compute_notice_assessment, derive_posture, group_of_filing,
                  notices_of, recompute_balance, APPEAL_WINDOW_DAYS,
                  DEFAULT_RESPONSE_DUE_DAYS)
from errors import ApiError, invalid
from models import find_filing, find_notice, ser_notice
from store import db
from util import add_days, money, opt_int, opt_num, req_dt, req_enum, req_num, req_str, ZERO
from web import (ANY_ROLE, body_json, bump, created, endpoint, new_record, ok, paginate)

bp = Blueprint("notices", __name__)

NOTICE_TYPES = ("MATH_ERROR", "NEXUS_INQUIRY", "PROPOSED_ASSESSMENT", "FINAL_ASSESSMENT")
OUTCOMES = ("SUSTAINED", "DENIED")


def guard_notice_state(notice, allowed):
    if notice["status"] not in allowed:
        raise ApiError("ERR_INVALID_NOTICE_STATE",
                       "The notice's status is %s, which is not a legal source state for this "
                       "operation." % notice["status"])


@bp.route("/salt/filings/<fid>/notices", methods=["POST"])
@endpoint(["TaxManager", "Controller"])
def create_notice(fid):
    filing = find_filing(fid)
    body = body_json()
    notice_type = req_enum(body, "notice_type", NOTICE_TYPES)
    state_notice_number = req_str(body, "state_notice_number")
    assessed_tax = req_num(body, "assessed_tax", minv=0)
    notice_date = req_dt(body, "notice_date")
    response_due_days = opt_int(body, "response_due_days", DEFAULT_RESPONSE_DUE_DAYS, minv=0)

    notice = new_record()
    notice.update({
        "filing_id": filing["id"],
        "notice_type": notice_type,
        "state_notice_number": state_notice_number,
        "assessed_tax": assessed_tax,
        "notice_date": notice_date,
        "response_due_days": response_due_days,
        "response_due_date": add_days(notice_date, response_due_days),
        "appeal_due_date": add_days(notice_date, APPEAL_WINDOW_DAYS),
        "status": "OPEN",
        "response_round": 0,
        "contested_amount": money(ZERO),
        "sustained_amount": money(ZERO),
        "penalty_amount": money(ZERO),
        "interest_amount": money(ZERO),
        "assessment_final_amount": money(ZERO),
    })
    db.notices[notice["id"]] = notice
    return created(ser_notice(notice))


@bp.route("/salt/notices/<nid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_notice(nid):
    return ok(ser_notice(find_notice(nid)))


@bp.route("/salt/filings/<fid>/notices", methods=["GET"])
@endpoint(ANY_ROLE)
def list_notices(fid):
    filing = find_filing(fid)
    return paginate(notices_of(filing), ser_notice)


@bp.route("/salt/notices/<nid>/respond", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def respond_notice(nid):
    notice = find_notice(nid)
    body = body_json()
    req_str(body, "response_summary")
    contested_amount = opt_num(body, "contested_amount", None, minv=0)

    guard_notice_state(notice, ("OPEN", "INFO_REQUESTED"))

    if db.clock > notice["response_due_date"]:
        raise ApiError("ERR_RESPONSE_DEADLINE_PASSED",
                       "The response deadline for this notice has passed.")

    notice["status"] = "RESPONDED"
    notice["response_round"] = notice["response_round"] + 1
    if contested_amount is not None:
        notice["contested_amount"] = money(contested_amount)
    bump(notice)
    return ok(ser_notice(notice))


@bp.route("/salt/notices/<nid>/request-info", methods=["POST"])
@endpoint(["TaxManager"])
def request_info(nid):
    notice = find_notice(nid)
    body = body_json()
    req_str(body, "info_requested")

    guard_notice_state(notice, ("RESPONDED",))

    notice["status"] = "INFO_REQUESTED"
    notice["response_due_date"] = add_days(db.clock, DEFAULT_RESPONSE_DUE_DAYS)
    bump(notice)
    return ok(ser_notice(notice))


@bp.route("/salt/notices/<nid>/appeal", methods=["POST"])
@endpoint(["Controller", "TaxManager"])
def appeal_notice(nid):
    notice = find_notice(nid)
    body = body_json()
    req_str(body, "appeal_grounds")

    guard_notice_state(notice, ("OPEN", "RESPONDED", "INFO_REQUESTED"))

    # PRD 3.8 lists the appellate window before the transmission precondition.
    if db.clock > notice["appeal_due_date"]:
        raise ApiError("ERR_APPEAL_DEADLINE_PASSED",
                       "The appeal deadline for this notice has passed.")

    filing = db.filings[notice["filing_id"]]
    if filing["preparation_status"] not in ("FILED", "AMENDED"):
        raise ApiError("ERR_INVALID_FILING_STATE",
                       "A notice on a return that was never transmitted cannot be appealed.")

    notice["status"] = "APPEAL_FILED"
    bump(notice)
    return ok(ser_notice(notice))


@bp.route("/salt/notices/<nid>/appeal-decision", methods=["POST"])
@endpoint(["TaxManager"])
def appeal_decision(nid):
    notice = find_notice(nid)
    body = body_json()
    outcome = req_enum(body, "outcome", OUTCOMES)
    sustained_amount = opt_num(body, "sustained_amount", None, minv=0)

    guard_notice_state(notice, ("APPEAL_FILED",))

    if outcome == "DENIED":
        sustained = money(ZERO)
    else:
        sustained = money(sustained_amount) if sustained_amount is not None else money(ZERO)
        if sustained > notice["assessed_tax"]:
            raise invalid("'sustained_amount' may not exceed the notice's assessed_tax")

    notice["status"] = "APPEAL_SUSTAINED" if outcome == "SUSTAINED" else "APPEAL_DENIED"
    notice["sustained_amount"] = sustained
    compute_notice_assessment(notice, sustained, db.clock)

    filing = db.filings[notice["filing_id"]]
    recompute_balance(filing)
    bump(notice)
    bump(filing)
    derive_posture(group_of_filing(filing))
    return ok(ser_notice(notice))


@bp.route("/salt/notices/<nid>/close", methods=["POST"])
@endpoint(["TaxManager"])
def close_notice(nid):
    notice = find_notice(nid)
    body = body_json()
    req_str(body, "closure_reason")

    guard_notice_state(notice, ("RESPONDED", "APPEAL_SUSTAINED", "APPEAL_DENIED"))

    notice["status"] = "CLOSED"
    bump(notice)
    return ok(ser_notice(notice))
