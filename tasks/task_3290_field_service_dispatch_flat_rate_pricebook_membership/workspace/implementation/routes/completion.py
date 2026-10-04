"""Two-call completion, accrual, and appointment cancellation (PRD 3.7, 3.10)."""

from flask import Blueprint

from constants import (ROLE_TECHNICIAN, ROLE_DISPATCHER, ROLE_MANAGER)
from common import body_json, require_roles, optional_str, require_str
from constants import clock
import store
import serializers
import calc
from errors import (ApiError, not_found, invalid_request,
                    ERR_INVALID_STATE, ERR_DESCRIPTION_TOO_SHORT,
                    ERR_DISCOUNT_FLOOR_REACHED, ERR_SEGREGATION_OF_DUTIES,
                    ERR_FORBIDDEN)
from response import object_ok

bp = Blueprint("completion", __name__)


def _get_appointment(appointment_id):
    row = store.appointments.get(appointment_id)
    if row is None:
        raise not_found("appointment")
    return row


def append_ledger_entry(technician_id, appointment_id, entry_type, amount_cents):
    """Ledger entries are append-mostly rows (PRD 2.4, 3.10)."""
    running = calc.ledger_total(technician_id) + amount_cents
    row = store.new_child_row(
        technician_id=technician_id,
        appointment_id=appointment_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
        running_total_cents=running,
        recorded_at_utc=clock.now(),
    )
    store.revenue_ledger_entries[row["id"]] = row
    return row


def _fulfil_visit(appointment):
    """The visit named by membership_visit_sequence_number (PRD 3.7)."""
    agreement_id = appointment.get("membership_agreement_id")
    sequence = appointment.get("membership_visit_sequence_number")
    if not agreement_id or sequence is None:
        return
    for visit in calc.agreement_visits(agreement_id):
        if int(visit["sequence_number"]) != int(sequence):
            continue
        if visit["status"] != "SCHEDULED":
            return
        visit["status"] = "COMPLETED"
        visit["completed_appointment_id"] = appointment["id"]
        visit["completed_at_utc"] = clock.now()
        store.touch(visit)
        calc.apply_revenue_recognition(agreement_id)
        agreement = store.membership_agreements.get(agreement_id)
        if agreement is not None:
            store.touch(agreement)
        return


def _reopen_visit(appointment):
    agreement_id = appointment.get("membership_agreement_id")
    sequence = appointment.get("membership_visit_sequence_number")
    if not agreement_id or sequence is None:
        return
    for visit in calc.agreement_visits(agreement_id):
        if int(visit["sequence_number"]) != int(sequence):
            continue
        if visit["status"] != "COMPLETED":
            return
        visit["status"] = "SCHEDULED"
        visit["completed_appointment_id"] = None
        visit["completed_at_utc"] = None
        store.touch(visit)
        agreement = store.membership_agreements.get(agreement_id)
        if agreement is not None:
            calc.apply_revenue_recognition(agreement_id)
            agreement["unearned_revenue_balance_cents"] = (
                int(agreement["annual_price_cents"]) - int(agreement["revenue_recognized_cents"]))
            store.touch(agreement)
        return


@bp.route("/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    require_roles([ROLE_TECHNICIAN])
    appointment = _get_appointment(appointment_id)
    payload = body_json()

    legal = (appointment["status"] == "DISPATCHED"
             and appointment["dispatch_status"] in ("DISPATCHED", "IN_SERVICE"))
    if not legal:
        raise ApiError(ERR_INVALID_STATE)

    # business guards, in the precedence order of PRD 2.10
    labor_base = calc.appointment_labor_base(appointment_id)
    quoted = appointment["quoted_price_cents"]
    if calc.discount_floor_breached(appointment_id, quoted):
        raise ApiError(ERR_DISCOUNT_FLOOR_REACHED)
    estimated = calc.appointment_estimated_hours(appointment_id)
    required_words = calc.required_description_words(estimated)
    if calc.supplied_description_words(payload) < required_words:
        raise ApiError(ERR_DESCRIPTION_TOO_SHORT)
    if payload.get("completion_description") is None:
        raise ApiError(ERR_DESCRIPTION_TOO_SHORT)

    technician = (store.technicians.get(appointment["technician_id"])
                  if appointment["technician_id"] else None)

    # ---- first hop: the van is on site -----------------------------------
    if appointment["dispatch_status"] == "DISPATCHED":
        appointment["dispatch_status"] = "IN_SERVICE"
        store.touch(appointment)
        if technician is not None:
            technician["status"] = "ON_JOB"
            store.touch(technician)
        return object_ok(serializers.appointment(appointment))

    # ---- second hop: the job is finished ---------------------------------
    appointment["status"] = "COMPLETED"
    appointment["dispatch_status"] = "RELEASED"
    store.touch(appointment)

    if technician is not None:
        technician["status"] = "AVAILABLE"
        store.touch(technician)

    sold_total = 0
    for line in calc.appointment_lines(appointment_id):
        if line["status"] != "SOLD":
            continue
        amount = calc.line_sold_price(line)
        sold_total += amount
        append_ledger_entry(technician["id"] if technician else appointment.get("technician_id"),
                            appointment_id, "ACCRUAL", amount)

    _fulfil_visit(appointment)

    branch = store.branches.get(appointment["branch_id"])
    if branch is not None:
        branch["updated_at"] = store.now_utc()

    return object_ok(serializers.appointment(appointment))


@bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    role, user_id = require_roles([ROLE_DISPATCHER, ROLE_MANAGER])
    appointment = _get_appointment(appointment_id)
    payload = body_json()
    optional_str(payload, "reason")

    if appointment["status"] == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE)
    if appointment["status"] == "COMPLETED" and role != ROLE_MANAGER:
        raise ApiError(ERR_FORBIDDEN)

    status = appointment["status"]

    if status == "SCHEDULED":
        if appointment["dispatch_status"] not in ("UNASSIGNED", "RELEASED"):
            raise ApiError(ERR_INVALID_STATE)
        appointment["status"] = "CANCELLED"
        store.touch(appointment)
        return object_ok(serializers.appointment(appointment))

    if status == "DISPATCHED":
        if appointment["dispatch_status"] != "DISPATCHED":
            raise ApiError(ERR_INVALID_STATE)
        accrual = _accrual_entry_for(appointment_id)
        if accrual is not None:
            raise ApiError(ERR_INVALID_STATE)
        technician_id = appointment.get("technician_id")
        technician = store.technicians.get(technician_id) if technician_id else None
        appointment["status"] = "CANCELLED"
        appointment["dispatch_status"] = "RELEASED"
        if technician_id and technician_id not in appointment["_released_technician_ids"]:
            appointment["_released_technician_ids"].append(technician_id)
        appointment["technician_id"] = None
        store.touch(appointment)
        if technician is not None:
            technician["status"] = "AVAILABLE"
            store.touch(technician)
        _detach_visit(appointment)
        branch = store.branches.get(appointment["branch_id"])
        if branch is not None:
            branch["updated_at"] = store.now_utc()
        return object_ok(serializers.appointment(appointment))

    # ---- COMPLETED: the compensating reversal (PRD 3.10) -----------------
    accrual = _accrual_entry_for(appointment_id)
    if accrual is None:
        raise ApiError(ERR_INVALID_STATE)
    if user_id == accrual["technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES)

    technician_id = accrual["technician_id"]
    sold_total = calc.appointment_sold_price(appointment_id)
    appointment["status"] = "CANCELLED"
    store.touch(appointment)
    append_ledger_entry(technician_id, appointment_id, "REVERSAL", -sold_total)
    _reopen_visit(appointment)
    return object_ok(serializers.appointment(appointment))


def _accrual_entry_for(appointment_id):
    for entry in store.revenue_ledger_entries.values():
        if entry["appointment_id"] == appointment_id and entry["entry_type"] == "ACCRUAL":
            return entry
    return None


def _detach_visit(appointment):
    """The visit stays owed; its completion fields remain null (PRD 3.10)."""
    agreement_id = appointment.get("membership_agreement_id")
    sequence = appointment.get("membership_visit_sequence_number")
    if not agreement_id or sequence is None:
        return
    for visit in calc.agreement_visits(agreement_id):
        if int(visit["sequence_number"]) == int(sequence) and visit["status"] == "SCHEDULED":
            visit["completed_appointment_id"] = None
            store.touch(visit)
            return