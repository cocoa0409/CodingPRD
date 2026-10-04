"""The dispatch board: eligibility, matching and the automatic quote (PRD 3.5)."""

from flask import Blueprint

from constants import ROLE_DISPATCHER
from common import require_roles, require_str, body_json
import store
import serializers
import calc
from errors import (ApiError, not_found, invalid_request,
                    ERR_NO_APPOINTMENT_LINES, ERR_NO_ELIGIBLE_TECHNICIAN,
                    ERR_TECHNICIAN_CAPACITY_EXCEEDED, ERR_INVALID_STATE)
from response import created, object_ok

bp = Blueprint("dispatch", __name__)


def _shift_ok(technician, window_start, window_end):
    for segment in technician["shift_segments"]:
        if segment["end_utc"] > window_start and segment["start_utc"] < window_end:
            return True
    return False


def required_skill_codes(appointment_id):
    codes = []
    for _line, task in calc.published_lines(appointment_id):
        code = task["required_skill_code"]
        if code not in codes:
            codes.append(code)
    return codes


def _technician_eligibility(appointment):
    appointment_id = appointment["id"]
    allowed = required_skill_codes(appointment_id)
    estimated = calc.appointment_estimated_hours(appointment_id)
    window_start = appointment["window_start_utc"]
    window_end = appointment["window_end_utc"]
    released = set(appointment.get("_released_technician_ids") or [])

    roster = list(store.technicians.values())

    # skill clause: a conjunction over every required code (PRD 3.5)
    skill_holders = [t for t in roster
                     if all(code in t["skill_codes"] for code in allowed)]
    if not skill_holders:
        raise ApiError(ERR_NO_ELIGIBLE_TECHNICIAN)

    def fully_eligible(t):
        if t["id"] in released:
            return False
        # PRD 3.5 names the released-from-this-appointment technician as the exclusion,
        # so a technician merely working another job (ON_SHIFT) is still a candidate;
        # load-levelling by `scheduled_hours` then spreads the day's work.
        if t["status"] not in ("AVAILABLE", "ON_SHIFT"):
            return False
        if not _shift_ok(t, window_start, window_end):
            return False
        if t["postal_code"][0:3] != appointment["postal_code"][0:3]:
            return False
        if appointment["branch_id"] != t["home_branch_id"]:
            return False
        return True

    def within_capacity(t):
        scheduled = calc.hours_of(calc.technician_scheduled_hours(t["id"]))
        ceiling = calc.hours_of(t["daily_capacity_hours"])
        if scheduled >= ceiling:
            return False
        return scheduled + calc.hours_of(estimated) <= ceiling

    candidates = [t for t in skill_holders if fully_eligible(t) and within_capacity(t)]
    if not candidates:
        overloaded = [t for t in skill_holders
                      if fully_eligible(t)
                      and calc.hours_of(calc.technician_scheduled_hours(t["id"]))
                      >= calc.hours_of(t["daily_capacity_hours"])]
        if overloaded:
            raise ApiError(ERR_TECHNICIAN_CAPACITY_EXCEEDED)
        raise ApiError(ERR_NO_ELIGIBLE_TECHNICIAN)

    candidates.sort(key=lambda t: (calc.hours_of(calc.technician_scheduled_hours(t["id"])),
                                   calc.hours_of(calc.technician_dispatched_hours(t["id"])),
                                   t["postal_code"],
                                   t["created_at"]))
    return candidates[0]


@bp.route("/dispatch/orders", methods=["POST"])
def dispatch_order():
    require_roles([ROLE_DISPATCHER])
    payload = body_json()
    appointment_id = require_str(payload, "appointment_id")
    appointment = store.appointments.get(appointment_id)
    if appointment is None:
        raise not_found("appointment")

    # state legality (priority 4)
    if appointment["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE)
    if appointment["dispatch_status"] not in ("UNASSIGNED", "RELEASED"):
        raise ApiError(ERR_INVALID_STATE)

    # appointment-lines-present guard (priority 5)
    if not calc.appointment_lines(appointment_id):
        raise ApiError(ERR_NO_APPOINTMENT_LINES)

    technician = _technician_eligibility(appointment)

    estimated = calc.appointment_estimated_hours(appointment_id)
    appointment["technician_id"] = technician["id"]
    appointment["status"] = "DISPATCHED"
    appointment["dispatch_status"] = "DISPATCHED"
    appointment["pricing_status"] = "AUTO_QUOTED"

    labor_base = calc.appointment_labor_base(appointment_id)
    discount = calc.invoice_discount_pct(appointment)
    appointment["quoted_price_cents"] = calc.cubic_quote(labor_base, discount)
    appointment["authorization_required"] = calc.authorization_required_for(
        appointment["quoted_price_cents"], labor_base)
    appointment["load_units_trace"] = calc.household_load_trace(appointment_id)
    store.touch(appointment)

    technician["status"] = "ON_SHIFT"
    store.touch(technician)

    # the dispatch touches the pricebook revisions the lines were drawn from
    for task_id in {line["pricebook_task_id"] for line in calc.appointment_lines(appointment_id)}:
        task = store.pricebook_tasks.get(task_id)
        if task is not None:
            store.touch(task)

    branch = store.branches.get(appointment["branch_id"])
    if branch is not None:
        branch["updated_at"] = store.now_utc()

    return created(serializers.appointment(appointment))