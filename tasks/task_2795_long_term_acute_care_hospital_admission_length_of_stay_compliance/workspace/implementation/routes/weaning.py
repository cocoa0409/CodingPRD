"""The ventilator weaning protocol (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import lookup
import serialize
import validate
from clock import now
from envelope import array_response, object_response
from errors import ApiError
from store import db, new_row, sorted_rows, touch

bp = Blueprint("weaning", __name__)

CO = auth.ROLE_COMPLIANCE_OFFICER
URN = auth.ROLE_UR_NURSE
AP = auth.ROLE_ATTENDING_PHYSICIAN
RIA = auth.ROLE_REVENUE_ANALYST

PLAN_STATUSES = ("SBT_TRIAL", "PROGRESSING", "REGRESSED", "LIBERATED", "VENT_DEPENDENT")
OPEN_PLAN_STATUSES = ("SBT_TRIAL", "PROGRESSING", "REGRESSED")
SBT_OUTCOMES = ("TOLERATED", "FAILED")
CLOSE_OUTCOMES = ("LIBERATED", "VENT_DEPENDENT")


@bp.route("/stays/<stay_id>/weaning-plans", methods=["POST"])
def create_weaning_plan(stay_id):
    body = validate.get_body()
    protocol_label = validate.opt_str(body, "protocol_label", 1, 40, default="STANDARD_SBT")
    vent_hours_total = validate.opt_num(body, "vent_hours_total", minimum=0,
                                       default=Decimal("0"))
    auth.require_role(URN)
    stay = lookup.stay(stay_id)

    if lookup.stay_weaning_plan(stay["id"]) is not None:
        raise ApiError("ERR_WEANING_PLAN_EXISTS", "The stay already has a ventilator weaning plan.")

    row = new_row("weaning_plans")
    row.update({
        "stay_id": stay["id"],
        "closed_by_physician_id": None,
        "protocol_label": protocol_label,
        "vent_hours_total": calc.hours(vent_hours_total),
        "current_step": 0,
        "sbt_attempt_count": 0,
        "consecutive_failed_sbt": 0,
        "max_tolerated_sbt_hours": calc.hours(Decimal("0")),
        "liberation_eligible": False,
        "last_progression_at": None,
        "status": "SBT_TRIAL",
        "closed_at": None,
    })
    db.weaning_plans[row["id"]] = row
    return object_response(serialize.weaning_plan(row), 201)


@bp.route("/weaning-plans/<plan_id>", methods=["GET"])
def get_weaning_plan(plan_id):
    auth.require_role(URN, AP, CO, RIA)
    return object_response(serialize.weaning_plan(lookup.weaning_plan(plan_id)))


@bp.route("/weaning-plans", methods=["GET"])
def list_weaning_plans():
    auth.require_role(URN, AP, CO, RIA)
    limit, offset = validate.pagination()
    stay_id = validate.query_str("stay_id")
    closed_by_physician_id = validate.query_str("closed_by_physician_id")
    status = validate.query_enum("status", PLAN_STATUSES)

    rows = list(db.weaning_plans.values())
    if stay_id is not None:
        rows = [r for r in rows if r["stay_id"] == stay_id]
    if closed_by_physician_id is not None:
        rows = [r for r in rows if r["closed_by_physician_id"] == closed_by_physician_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.weaning_plan(r) for r in page], limit, offset, len(rows))


def _documentation_is_fresh(plan):
    """PRD 2.8 rule 32: respiratory-therapy and physician notes since the last progression."""
    boundary = plan["last_progression_at"] or plan["created_at"]
    seen = set()
    for note in lookup.stay_notes(plan["stay_id"]):
        if note["documented_at"] >= boundary:
            seen.add(note["discipline"])
    return "RESPIRATORY_THERAPY" in seen and "PHYSICIAN" in seen


@bp.route("/weaning-plans/<plan_id>/record-sbt", methods=["POST"])
def record_sbt(plan_id):
    body = validate.get_body()
    outcome = validate.req_enum(body, "outcome", SBT_OUTCOMES)
    sbt_hours = validate.req_num(body, "sbt_hours", minimum=0)
    vent_hours_since_last = validate.req_num(body, "vent_hours_since_last", minimum=0)
    auth.require_role(URN)
    plan = lookup.weaning_plan(plan_id)

    if plan["status"] not in OPEN_PLAN_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "The weaning plan is already closed.")

    if outcome == "TOLERATED" and not _documentation_is_fresh(plan):
        raise ApiError("ERR_IDT_DOCUMENTATION_STALE",
                       "A tolerated trial requires respiratory-therapy and physician notes "
                       "documented since the last progression.")

    plan["sbt_attempt_count"] = plan["sbt_attempt_count"] + 1
    plan["vent_hours_total"] = calc.hours(
        Decimal(plan["vent_hours_total"]) + Decimal(vent_hours_since_last))

    if outcome == "TOLERATED":
        plan["current_step"] = plan["current_step"] + 1
        plan["consecutive_failed_sbt"] = 0
        if Decimal(sbt_hours) > Decimal(plan["max_tolerated_sbt_hours"]):
            plan["max_tolerated_sbt_hours"] = calc.hours(sbt_hours)
        plan["last_progression_at"] = now()
        plan["status"] = "PROGRESSING"
    else:
        plan["consecutive_failed_sbt"] = plan["consecutive_failed_sbt"] + 1
        if plan["consecutive_failed_sbt"] >= 2:
            plan["current_step"] = plan["current_step"] - 1
            if plan["current_step"] < 0:
                plan["current_step"] = 0
            plan["status"] = "REGRESSED"

    plan["liberation_eligible"] = plan["current_step"] >= calc.PROGRESSION_STEPS_REQUIRED
    touch(plan)
    return object_response(serialize.weaning_plan(plan))


@bp.route("/weaning-plans/<plan_id>/close", methods=["POST"])
def close_weaning_plan(plan_id):
    body = validate.get_body()
    outcome = validate.req_enum(body, "outcome", CLOSE_OUTCOMES)
    auth.require_role(AP)
    plan = lookup.weaning_plan(plan_id)
    physician = auth.acting_physician()

    if plan["status"] not in OPEN_PLAN_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "The weaning plan is already closed.")

    if outcome == "LIBERATED":
        if not plan["liberation_eligible"]:
            raise ApiError("ERR_WEANING_PROGRESSION_INSUFFICIENT",
                           "Liberation requires at least two progression steps.")
        if plan["status"] != "PROGRESSING":
            raise ApiError("ERR_INVALID_STATE",
                           "A LIBERATED close is reachable only from PROGRESSING.")
    else:
        if plan["sbt_attempt_count"] < calc.MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT:
            raise ApiError("ERR_INSUFFICIENT_SBT_ATTEMPTS",
                           "A VENT_DEPENDENT close requires at least three trial records.")

    if physician["specialty"] != "PULMONOLOGY" or physician["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_NOT_CREDENTIALED",
                       "Closing a weaning plan requires an ACTIVE PULMONOLOGY physician.")

    plan["status"] = outcome
    plan["closed_at"] = now()
    plan["closed_by_physician_id"] = physician["id"]
    touch(plan)
    return object_response(serialize.weaning_plan(plan))
