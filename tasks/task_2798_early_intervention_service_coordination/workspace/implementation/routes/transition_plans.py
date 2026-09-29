"""Transition planning to preschool services and the LEA notification."""
from flask import Blueprint, request

import domain as D
from auth import STAFF_READ, endpoint, require_owner
from envelope import paginate, single
from errors import fail
from helpers import (get_ifsp, get_transition_plan, not_future,
                     ser_transition_plan)
from services import compute
from store import (clock_date, day_count, db, flush, new_row, ordered, pd,
                   set_fields)
from validate import Field, parse_body, v_bool, v_date, v_id, v_int, v_token

bp = Blueprint("transition_plans", __name__)

TRANSITION_PLAN_LIVE = ("DRAFT", "NOTIFIED", "OPT_OUT", "COMPLETE")


@bp.route("/ei/transition-plans", methods=["POST"])
@endpoint(["ServiceCoordinator"])
def create_transition_plan():
    payload = parse_body([
        Field("ifsp_id", v_id()),
        Field("target_conference_date", v_date()),
        Field("conference_held_date", v_date(), required=False),
        Field("transition_steps_count", v_int(0, 20), required=False, default=0),
    ])
    plan = get_ifsp(payload["ifsp_id"])
    referral = compute.referral_of_ifsp(plan)
    require_owner(referral["coordinator_id"] if referral else None)
    if plan["status"] != "ACTIVE":
        fail("ERR_IFSP_STATE_INVALID",
             "A transition plan may only be opened against an ACTIVE plan.")
    for existing in compute.ifsp_transition_plans(plan["id"]):
        if existing["status"] in TRANSITION_PLAN_LIVE:
            fail("ERR_TRANSITION_PLAN_DUPLICATE",
                 "The plan already carries a transition plan.")
    third_birthday = compute.third_birthday_of(referral) if referral else None
    lead = day_count(clock_date(), third_birthday)
    if lead is None or lead > D.TRANSITION_WINDOW_OPEN_DAYS:
        fail("ERR_TRANSITION_WINDOW_NOT_OPEN",
             "Transition planning opens in the final nine months before the "
             "child's third birthday.")
    transition_plan = new_row({
        "ifsp_id": plan["id"],
        "target_conference_date": payload["target_conference_date"],
        "conference_held_date": payload["conference_held_date"],
        "transition_steps_count": payload["transition_steps_count"],
        "lea_code": None,
        "notification_date": None,
        "notification_lead_days": None,
        "notification_compliance": None,
        "family_opt_out": False,
        "opt_out_signed_date": None,
        "status": "DRAFT",
    })
    db.transition_plans[transition_plan["id"]] = transition_plan
    flush()
    return single(ser_transition_plan(transition_plan), 201)


@bp.route("/ei/transition-plans/<transition_plan_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_transition_plan(transition_plan_id):
    return single(ser_transition_plan(get_transition_plan(transition_plan_id)))


@bp.route("/ei/transition-plans", methods=["GET"])
@endpoint(STAFF_READ)
def list_transition_plans():
    rows = ordered(db.transition_plans)
    ifsp_id = request.args.get("ifsp_id")
    status = request.args.get("status")
    if ifsp_id is not None:
        rows = [r for r in rows if r["ifsp_id"] == ifsp_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_transition_plan)


@bp.route("/ei/transition-plans/<transition_plan_id>/notify-lea",
          methods=["POST"])
@endpoint(["ServiceCoordinator"])
def notify_lea(transition_plan_id):
    payload = parse_body([
        Field("notification_date", v_date()),
        Field("family_opt_out", v_bool()),
        Field("lea_code", v_token(), required=False),
        Field("opt_out_signed_date", v_date(), required=False),
    ])
    opted_out = payload["family_opt_out"]
    if opted_out:
        if not payload["opt_out_signed_date"] or payload["lea_code"]:
            fail("ERR_INVALID_REQUEST",
                 "An opted-out notification carries an opt_out_signed_date and "
                 "no lea_code.")
    else:
        if not payload["lea_code"] or payload["opt_out_signed_date"]:
            fail("ERR_INVALID_REQUEST",
                 "A notification carries a lea_code and no "
                 "opt_out_signed_date.")
    transition_plan = get_transition_plan(transition_plan_id)
    plan = db.ifsps.get(transition_plan["ifsp_id"])
    referral = compute.referral_of_ifsp(plan) if plan else None
    require_owner(referral["coordinator_id"] if referral else None)
    if transition_plan["status"] != "DRAFT":
        fail("ERR_TRANSITION_PLAN_STATE_INVALID",
             "Only a DRAFT transition plan may record a notification.")
    if not opted_out:
        if (not transition_plan["conference_held_date"]
                or (transition_plan["transition_steps_count"] or 0) < 1):
            fail("ERR_TRANSITION_PLAN_INCOMPLETE",
                 "A notified transition plan needs a held conference and at "
                 "least one documented transition step.")
    not_future(payload["notification_date"], "notification_date")
    if payload["opt_out_signed_date"]:
        not_future(payload["opt_out_signed_date"], "opt_out_signed_date")
    third_birthday = compute.third_birthday_of(referral) if referral else None
    lead = day_count(pd(payload["notification_date"]), third_birthday)
    if lead is None or lead < 0:
        fail("ERR_NOTIFICATION_AFTER_THIRD_BIRTHDAY",
             "The notification is dated after the child's third birthday.")
    if opted_out:
        compliance = "WAIVED_OPT_OUT"
    elif lead > D.TRANSITION_WINDOW_OPEN_DAYS:
        compliance = "EARLY"
    elif lead >= D.TRANSITION_NOTIFICATION_MIN_LEAD_DAYS:
        compliance = "TIMELY"
    else:
        compliance = "LATE"
    set_fields(transition_plan, {
        "status": "OPT_OUT" if opted_out else "NOTIFIED",
        "lea_code": payload["lea_code"],
        "notification_date": payload["notification_date"],
        "notification_lead_days": lead,
        "notification_compliance": compliance,
        "family_opt_out": opted_out,
        "opt_out_signed_date": payload["opt_out_signed_date"],
    })
    flush()
    return single(ser_transition_plan(transition_plan))
