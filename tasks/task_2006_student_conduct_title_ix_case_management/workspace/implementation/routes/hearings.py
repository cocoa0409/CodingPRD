"""Hearing and CrossExamQuestion endpoints (PRD 3.4)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_ADVISOR_REQUIRED,
    ERR_HEARING_TIME_CONFLICT, ERR_NOTICE_LEAD_TIME_INSUFFICIENT,
    ERR_ACTIVE_HEARING_EXISTS, ERR_NOT_HEARING_DECISION_MAKER,
    ERR_PENDING_QUESTIONS_REMAIN, ERR_QUESTIONER_NOT_CASE_ADVISOR,
)
from middleware import authorized, check_case_read_access, STAFF_READ_ROLES, ALL_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    check_not_case_party, check_segregation,
    MODALITIES, QUESTION_TARGET_SIDES, QUESTION_RULINGS, LIVE_HEARING_STATES,
    HEARING_BUFFER_MINUTES,
)
from util import clock_iso, clock_dt, parse_datetime
from validate import (
    get_body, req_str, req_enum, req_datetime, req_int, require_path,
    require_profile_fk, as_datetime,
)

bp = Blueprint("hearings", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party", "Advisor"]


def _occupancy(hearing):
    start = parse_datetime(hearing["scheduled_at"])
    return start, start + timedelta(minutes=hearing["estimated_duration_minutes"])


def _calendar_conflict(dm_id, scheduled_at, duration_minutes):
    """Non-cancelled occupancy intervals for one decision-maker must not overlap
    and must keep a 60-minute buffer on both sides (exactly 60 passes)."""
    new_start = parse_datetime(scheduled_at)
    new_end = new_start + timedelta(minutes=duration_minutes)
    buffer = timedelta(minutes=HEARING_BUFFER_MINUTES)
    for h in db["hearings"].values():
        if h["decision_maker_id"] != dm_id or h["status"] == "CANCELLED":
            continue
        old_start, old_end = _occupancy(h)
        if not (new_end + buffer <= old_start or old_end + buffer <= new_start):
            return True
    return False


@bp.post("/cases/<cid>/hearings")
def schedule_hearing(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 4: case must be in HEARING_PREPARATION (only packet finalize produces it).
    if case["status"] != "HEARING_PREPARATION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not HEARING_PREPARATION")
    # Tier 3: body FK existence.
    require_profile_fk(body, "decision_maker_id")
    dm_id = body.get("decision_maker_id")
    scheduled_at = as_datetime(body, "scheduled_at")
    duration = body.get("estimated_duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int):
        duration_ok = False
    else:
        duration_ok = duration > 0
    if isinstance(dm_id, str):
        # Tier 5: party bar then segregation (safety outranks temporal).
        check_not_case_party(case, dm_id)
        check_segregation(case, dm_id, for_function="decision_maker")
    # Tier 6: future, 10-day lead, then calendar buffer.
    now = clock_dt()
    if scheduled_at is not None and duration_ok:
        if parse_datetime(scheduled_at) <= now:
            raise_error(ERR_HEARING_TIME_CONFLICT,
                        "scheduled_at must be strictly in the future")
        if (parse_datetime(scheduled_at) - now).total_seconds() < 10 * 86400:
            raise_error(ERR_NOTICE_LEAD_TIME_INSUFFICIENT,
                        "hearings require at least 10 days of lead time")
        if isinstance(dm_id, str) and _calendar_conflict(dm_id, scheduled_at, duration):
            raise_error(ERR_HEARING_TIME_CONFLICT,
                        "decision-maker calendar overlap or buffer under 60 minutes")
    # Tier 7: one live hearing per case.
    if any(h["case_id"] == cid and h["status"] in LIVE_HEARING_STATES
           for h in db["hearings"].values()):
        raise_error(ERR_ACTIVE_HEARING_EXISTS,
                    "another hearing on this case is still live")
    # Tier 11: schema.
    decision_maker_id = req_str(body, "decision_maker_id")
    scheduled_at = req_datetime(body, "scheduled_at")
    estimated_duration_minutes = req_int(body, "estimated_duration_minutes", positive=True)
    modality = req_enum(body, "modality", MODALITIES)

    rec = new_record("hearings", {
        "case_id": cid,
        "decision_maker_id": decision_maker_id,
        "scheduled_at": scheduled_at,
        "estimated_duration_minutes": estimated_duration_minutes,
        "modality": modality,
        "status": "SCHEDULED",
        "adjourn_reason": None,
        "convened_at": None,
    })
    append_event(cid, "HEARING_SCHEDULED", caller,
                 {"hearing_id": rec["id"], "scheduled_at": scheduled_at})
    auto_notice(cid, "HEARING", "BOTH", "A live hearing has been scheduled.",
                scheduled_event_at=scheduled_at)
    append_event(cid, "NOTICE_SENT", caller, {"notice_type": "HEARING", "recipient_side": "BOTH"})
    bump_case(case)
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/hearings")
def list_hearings(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [h for h in db["hearings"].values() if h["case_id"] == cid]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/hearings/<hid>")
def get_hearing(hid):
    caller = authorized(READ_ROLES)
    hearing = require_path("hearings", hid)
    case = get_case(hearing["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(hearing))


@bp.get("/hearings")
def list_hearings_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator", "DecisionMaker"])
    items = list(db["hearings"].values())
    items = apply_filters(items, {
        "decision_maker_id": request.args.get("decision_maker_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def _both_parties_have_active_advisors(case):
    for side, pid in (("COMPLAINANT", case["complainant_id"]),
                      ("RESPONDENT", case["respondent_id"])):
        if not any(a["case_id"] == case["id"] and a["party_side"] == side
                   and a["status"] == "ACTIVE"
                   for a in db["advisor_appointments"].values()):
            return False
    return True


@bp.post("/hearings/<hid>/convene")
def convene_hearing(hid):
    caller = authorized(["DecisionMaker"])
    hearing = require_path("hearings", hid)
    case = get_case(hearing["case_id"])
    if hearing["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not SCHEDULED")
    if case["status"] != "HEARING_PREPARATION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not HEARING_PREPARATION")
    # Tier 5: both parties must hold ACTIVE advisors.
    if not _both_parties_have_active_advisors(case):
        raise_error(ERR_ADVISOR_REQUIRED,
                    "both parties must hold an ACTIVE advisor appointment before convening")
    # Tier 6: the clock must have reached the scheduled start.
    if clock_dt() < parse_datetime(hearing["scheduled_at"]):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "the hearing's scheduled time has not yet arrived")
    # Tier 8: identity binding to this hearing's decision-maker.
    if caller.user_id != hearing["decision_maker_id"]:
        raise_error(ERR_NOT_HEARING_DECISION_MAKER,
                    "only this hearing's decision-maker may convene it")
    hearing["status"] = "IN_SESSION"
    hearing["convened_at"] = clock_iso()
    touch(hearing)
    case["status"] = "HEARING_IN_PROGRESS"
    bump_case(case)
    append_event(case["id"], "HEARING_CONVENED", caller,
                 {"hearing_id": hid, "status": "IN_SESSION"})
    return success_object(public(hearing))


@bp.post("/hearings/<hid>/adjourn")
def adjourn_hearing(hid):
    caller = authorized(["DecisionMaker"])
    hearing = require_path("hearings", hid)
    if hearing["status"] != "IN_SESSION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not IN_SESSION")
    body = get_body()
    adjourn_reason = req_str(body, "adjourn_reason")
    hearing["status"] = "ADJOURNED"
    hearing["adjourn_reason"] = adjourn_reason
    touch(hearing)
    append_event(hearing["case_id"], "HEARING_ADJOURNED", caller,
                 {"hearing_id": hid, "status": "ADJOURNED"})
    return success_object(public(hearing))


@bp.post("/hearings/<hid>/reconvene")
def reconvene_hearing(hid):
    caller = authorized(["DecisionMaker"])
    hearing = require_path("hearings", hid)
    if hearing["status"] != "ADJOURNED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not ADJOURNED")
    hearing["status"] = "IN_SESSION"
    hearing["adjourn_reason"] = None
    touch(hearing)
    append_event(hearing["case_id"], "HEARING_RECONVENED", caller,
                 {"hearing_id": hid, "status": "IN_SESSION"})
    return success_object(public(hearing))


@bp.post("/hearings/<hid>/cancel")
def cancel_hearing(hid):
    caller = authorized(["DecisionMaker", "TitleIXCoordinator"])
    hearing = require_path("hearings", hid)
    if hearing["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not SCHEDULED")
    hearing["status"] = "CANCELLED"
    touch(hearing)
    append_event(hearing["case_id"], "HEARING_CANCELLED", caller,
                 {"hearing_id": hid, "status": "CANCELLED"})
    return success_object(public(hearing))


@bp.post("/hearings/<hid>/close-cross-exam")
def close_cross_exam(hid):
    caller = authorized(["DecisionMaker"])
    hearing = require_path("hearings", hid)
    case = get_case(hearing["case_id"])
    if hearing["status"] != "IN_SESSION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not IN_SESSION")
    # Tier 7: zero PENDING questions on the hearing.
    if any(q["hearing_id"] == hid and q["ruling"] == "PENDING"
           for q in db["cross_exam_questions"].values()):
        raise_error(ERR_PENDING_QUESTIONS_REMAIN,
                    "cross-exam questions are still PENDING on this hearing")
    # Tier 8: identity binding.
    if caller.user_id != hearing["decision_maker_id"]:
        raise_error(ERR_NOT_HEARING_DECISION_MAKER,
                    "only this hearing's decision-maker may close cross-examination")
    hearing["status"] = "DELIBERATION"
    touch(hearing)
    case["status"] = "DELIBERATION"
    bump_case(case)
    append_event(case["id"], "CROSS_EXAM_CLOSED", caller,
                 {"hearing_id": hid, "status": "DELIBERATION"})
    return success_object(public(hearing))


# ---------------------------------------------------------------------------
# CrossExamQuestion
# ---------------------------------------------------------------------------

@bp.post("/hearings/<hid>/cross-exam-questions")
def ask_question(hid):
    caller = authorized(["Advisor"])
    hearing = require_path("hearings", hid)
    case = get_case(hearing["case_id"])
    body = get_body()
    # Tier 3: body FK existence.
    require_profile_fk(body, "asked_by_advisor_id")
    if hearing["status"] != "IN_SESSION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not IN_SESSION")
    # Tier 5: the asker must hold an ACTIVE appointment on this case and target
    # the opposing side of their own appointment.
    target_side = body.get("target_side")
    appointment = None
    for a in db["advisor_appointments"].values():
        if a["case_id"] == case["id"] and a["advisor_id"] == caller.user_id \
                and a["status"] == "ACTIVE":
            appointment = a
            break
    asked_by = body.get("asked_by_advisor_id")
    if appointment is None or asked_by != caller.user_id \
            or target_side not in QUESTION_TARGET_SIDES \
            or target_side == appointment["party_side"]:
        raise_error(ERR_QUESTIONER_NOT_CASE_ADVISOR,
                    "the asker must hold an ACTIVE appointment and cross-examine the opposing side")
    # Tier 11: schema.
    req_str(body, "asked_by_advisor_id")
    target_side = req_enum(body, "target_side", QUESTION_TARGET_SIDES)
    question_text = req_str(body, "question_text")

    sequence = sum(1 for q in db["cross_exam_questions"].values() if q["hearing_id"] == hid) + 1
    rec = new_record("cross_exam_questions", {
        "hearing_id": hid,
        "sequence": sequence,
        "asked_by_advisor_id": caller.user_id,
        "target_side": target_side,
        "question_text": question_text,
        "ruling": "PENDING",
        "ruling_reason": None,
    })
    append_event(case["id"], "QUESTION_ASKED", caller,
                 {"question_id": rec["id"], "hearing_id": hid, "sequence": sequence})
    return success_object(public(rec), 201)


@bp.get("/hearings/<hid>/cross-exam-questions")
def list_questions(hid):
    caller = authorized(READ_ROLES)
    hearing = require_path("hearings", hid)
    case = get_case(hearing["case_id"])
    check_case_read_access(caller, case)
    items = [q for q in db["cross_exam_questions"].values() if q["hearing_id"] == hid]
    items = apply_filters(items, {"ruling": request.args.get("ruling")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/cross-exam-questions/<qid>")
def get_question(qid):
    caller = authorized(READ_ROLES)
    question = require_path("cross_exam_questions", qid)
    hearing = require_path("hearings", question["hearing_id"])
    case = get_case(hearing["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(question))


@bp.get("/cross-exam-questions")
def list_questions_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["cross_exam_questions"].values())
    items = apply_filters(items, {
        "asked_by_advisor_id": request.args.get("asked_by_advisor_id"),
        "ruling": request.args.get("ruling"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/cross-exam-questions/<qid>/rule")
def rule_question(qid):
    caller = authorized(["DecisionMaker"])
    question = require_path("cross_exam_questions", qid)
    hearing = require_path("hearings", question["hearing_id"])
    if question["ruling"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"question ruling is already {question['ruling']}")
    if hearing["status"] != "IN_SESSION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"hearing is {hearing['status']}, not IN_SESSION")
    # Tier 8: only this hearing's decision-maker rules.
    if caller.user_id != hearing["decision_maker_id"]:
        raise_error(ERR_NOT_HEARING_DECISION_MAKER,
                    "only this hearing's decision-maker may rule on questions")
    body = get_body()
    ruling = req_enum(body, "ruling", QUESTION_RULINGS)
    if ruling == "DISALLOWED":
        ruling_reason = req_str(body, "ruling_reason")
        question["ruling_reason"] = ruling_reason
        question["ruling"] = "DISALLOWED"
    else:
        question["ruling"] = "ALLOWED"
    touch(question)
    append_event(hearing["case_id"], "QUESTION_RULED", caller,
                 {"question_id": qid, "ruling": question["ruling"]})
    return success_object(public(question))
