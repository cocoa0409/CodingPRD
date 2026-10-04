"""The observed dose pipeline (PRD 3.4, 3.5; SCAFFOLD DoseDispense state machine).

Every precondition is checked in the global priority order of PRD 2.11:
state (7) before safety (8) before the constraint checks (15, 16, 17, 21, 22).
"""
from datetime import timedelta

import db
from constants import DOSE_OPEN, DOSE_TERMINAL
from errors import ApiError
from services import carry, entity, inventory, patient as patient_svc, program as program_svc, stability
from services.num import r2


def dose_of(dose_id):
    row = db.dose_dispenses.get(dose_id)
    if row is None:
        raise ApiError("ERR_DOSE_NOT_FOUND", "No DoseDispense with the supplied id")
    return row


def order_of(dose):
    return db.dose_orders.get(dose.get("dose_order_id"))


def order_of_for_patient(patient):
    return carry.active_order_for_patient(patient["id"])


def patient_of(dose):
    return db.patients.get(dose.get("patient_id"))


def program_of(dose):
    return db.programs.get(dose.get("program_id"))


# ---------------------------------------------------------------------------
# Clinic-day rules (priority 13)
# ---------------------------------------------------------------------------
def _open_day_code(moment):
    return ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][moment.weekday()]


def clinic_window(program, on_date):
    start_text = program.get("clinic_hours_start") or "00:00"
    end_text = program.get("clinic_hours_end") or "23:59"
    start_h, start_m = [int(p) for p in start_text.split(":")]
    end_h, end_m = [int(p) for p in end_text.split(":")]
    start = on_date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = on_date.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start, end


def check_clinic_day(program, dose_date, scheduled_datetime, patient_id, ignore_dose_id=None):
    """Priority 13: open day, clinic window, slot capacity and per-patient uniqueness."""
    moment = db.parse_iso(scheduled_datetime)
    date_value = db.parse_date(dose_date)
    if moment is None or date_value is None:
        raise ApiError("ERR_INVALID_REQUEST", "dose_date and scheduled_datetime are required")
    if _open_day_code(date_value) not in (program.get("open_days") or []):
        raise ApiError("ERR_NOT_AN_OPEN_DAY", "dose_date is not one of the program's open days")
    start, end = clinic_window(program, date_value)
    if moment < start or moment > end:
        raise ApiError("ERR_OUTSIDE_CLINIC_HOURS", "scheduled_datetime is outside the clinic window")

    occupants = 0
    for row in db.dose_dispenses.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("dose_date") != dose_date:
            continue
        if row.get("status") in DOSE_TERMINAL:
            continue
        if ignore_dose_id and row["id"] == ignore_dose_id:
            continue
        occupants += 1
    if occupants >= (program.get("max_daily_dose_slots") or 0):
        raise ApiError("ERR_NO_DOSE_CAPACITY", "The open day already holds max_daily_dose_slots doses")

    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id or row.get("dose_date") != dose_date:
            continue
        if row.get("status") in DOSE_TERMINAL:
            continue
        if ignore_dose_id and row["id"] == ignore_dose_id:
            continue
        raise ApiError(
            "ERR_DUPLICATE_ACTIVE_DOSE",
            "The patient already has a non-terminal dose on this dose_date",
        )


def check_checkin_window(program, dose):
    """Check-in is accepted until window end on the dose day plus the grace period."""
    date_value = db.parse_date(dose.get("dose_date"))
    if date_value is None:
        return
    _, end = clinic_window(program, date_value)
    deadline = end + timedelta(minutes=program.get("dose_checkin_grace_minutes") or 0)
    if db.clock_dt() > deadline:
        raise ApiError("ERR_OUTSIDE_CLINIC_HOURS", "The instant is outside the clinic window")


# ---------------------------------------------------------------------------
# check-in
# ---------------------------------------------------------------------------
def check_in(dose, actor):
    # §2.11 pins the order: the priority-7 state precondition is evaluated before
    # the priority-8 posture gate, so "when a request violates both a state rule
    # and a safety rule, the state rule wins and the caller sees the 409
    # transition error rather than the safety error".
    if dose.get("status") != "SCHEDULED":
        raise ApiError("ERR_DOSE_NOT_SCHEDULED", "DoseDispense is not SCHEDULED")
    if dose.get("source_type") == "TAKE_HOME_ISSUANCE":
        raise ApiError(
            "ERR_TAKE_HOME_NOT_CHECKED_IN",
            "A take-home issuance dose is never checked in",
        )
    program = program_of(dose)
    if actor.role == "Nurse" and actor.program_id and program and actor.program_id != program["id"]:
        raise ApiError("ERR_NURSE_NOT_IN_PROGRAM", "The acting nurse belongs to another program")
    if program is not None:
        check_checkin_window(program, dose)
        program_svc.ensure_not_frozen(program)
    dose["status"] = "ARRIVED_AT_CLINIC"
    dose["arrived_at"] = db.fmt_dt(db.clock_dt())
    db.stamp(dose)
    return dose


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def verify(dose, identity_matched, actor):
    if dose.get("status") != "ARRIVED_AT_CLINIC":
        raise ApiError("ERR_DOSE_NOT_ARRIVED", "DoseDispense is not ARRIVED_AT_CLINIC")
    if not identity_matched:
        dose["status"] = "VERIFICATION_FAILED"
        dose["verification_result"] = "FAILED"
        dose["verification_staff_id"] = actor.user_id
        db.stamp(dose)
        return dose

    program = program_of(dose)
    if actor.role == "Nurse" and actor.program_id and program and actor.program_id != program["id"]:
        raise ApiError("ERR_NURSE_NOT_IN_PROGRAM", "The acting nurse belongs to another program")
    patient = patient_of(dose)
    if patient is None or patient.get("status") not in ("ACTIVE", "ADMITTED", "SUSPENDED_NON_COMPLIANT"):
        raise ApiError("ERR_PATIENT_NOT_DOSABLE", "The patient cannot receive a verified dose")
    order = order_of(dose)
    if order is not None and r2(dose.get("ordered_mg") or 0.0) != r2(order.get("ordered_daily_mg") or 0.0):
        raise ApiError(
            "ERR_DOSE_ORDER_CHANGED",
            "The dose's frozen ordered milligrams no longer match the order",
        )
    dose["status"] = "NURSE_VERIFIED"
    dose["verification_result"] = "PASSED"
    dose["verification_staff_id"] = actor.user_id
    db.stamp(dose)
    return dose


# ---------------------------------------------------------------------------
# dispense
# ---------------------------------------------------------------------------
def dispense(dose, body, actor):
    program = program_of(dose)
    order = order_of(dose)

    # priority 5: a named lot must exist
    requested_lot_id = body.get("inventory_lot_id")
    named_lot = None
    if requested_lot_id:
        named_lot = db.inventory_lots.get(requested_lot_id)
        if named_lot is None:
            raise ApiError("ERR_LOT_NOT_FOUND", "No InventoryLot with the supplied id")

    # priority 7
    if dose.get("status") != "NURSE_VERIFIED":
        raise ApiError("ERR_DOSE_NOT_VERIFIED", "DoseDispense is not NURSE_VERIFIED")
    # priority 8
    if program is not None:
        program_svc.ensure_normal_for_medication(program)

    dispensed_mg = float(body.get("dispensed_mg") or 0.0)
    wasted_mg = float(body.get("wasted_mg") or 0.0)
    returned_mg = float(body.get("returned_mg") or 0.0)
    witness = body.get("witness_staff_id")
    ordered_mg = dose.get("ordered_mg") or 0.0

    # priority 15: mass balance, every component non-negative
    if dispensed_mg < 0 or wasted_mg < 0 or returned_mg < 0:
        raise ApiError("ERR_DOSE_MASS_MISMATCH", "Every mass component must be non-negative")
    if r2(dispensed_mg + wasted_mg + returned_mg) != r2(ordered_mg):
        raise ApiError(
            "ERR_DOSE_MASS_MISMATCH",
            "dispensed_mg + wasted_mg + returned_mg must equal ordered_mg",
        )
    # priority 16: the cumulative view
    prior = (
        (dose.get("dispensed_mg") or 0.0)
        + (dose.get("wasted_mg") or 0.0)
        + (dose.get("returned_mg") or 0.0)
    )
    if r2(prior + dispensed_mg + wasted_mg + returned_mg) > r2(ordered_mg):
        raise ApiError("ERR_PARTIAL_EXCEEDS_ORDERED", "The cumulative movement exceeds ordered_mg")
    # priority 17: witness for waste
    if wasted_mg > 0:
        if not witness or str(witness) == str(actor.user_id):
            raise ApiError(
                "ERR_WITNESS_REQUIRED",
                "A wasted quantity requires a witness distinct from the acting staff member",
            )

    # priority 21: the inventory ceiling against the selected lot
    lot = named_lot if named_lot is not None else inventory.select_lot(dose, order)
    if lot is not None and inventory.eff(lot.get("running_on_hand_mg")) < ordered_mg:
        raise ApiError(
            "ERR_INVENTORY_CEILING_EXCEEDED",
            "The dose exceeds the selected lot's running_on_hand_mg",
        )
    # priority 22: lot usability
    if named_lot is not None:
        if named_lot.get("status") == "QUARANTINED":
            raise ApiError("ERR_LOT_QUARANTINED", "The lot is QUARANTINED")
        if inventory.lot_is_expired(named_lot):
            raise ApiError("ERR_LOT_EXPIRED", "The lot is expired")
    if lot is None:
        raise ApiError("ERR_NO_ELIGIBLE_LOT", "The lot selector candidate set is empty")

    dose["dispensed_mg"] = r2(dispensed_mg)
    dose["wasted_mg"] = r2(wasted_mg)
    dose["returned_mg"] = r2(returned_mg)
    dose["inventory_lot_id"] = lot["id"]
    dose["witness_staff_id"] = witness
    dose["status"] = "DISPENSED"

    inventory.append_transaction(
        lot,
        "DISPENSE",
        -dispensed_mg,
        patient_id=dose.get("patient_id"),
        dose_dispense_id=dose["id"],
    )
    if wasted_mg > 0:
        inventory.append_transaction(
            lot,
            "WASTE",
            -wasted_mg,
            patient_id=dose.get("patient_id"),
            dose_dispense_id=dose["id"],
            witness_staff_id=witness,
        )
    if returned_mg > 0:
        inventory.append_transaction(
            lot,
            "RETURN",
            returned_mg,
            patient_id=dose.get("patient_id"),
            dose_dispense_id=dose["id"],
        )

    if dose.get("source_type") == "TAKE_HOME_ISSUANCE":
        ledger = carry.ensure_ledger_for_patient(patient_of(dose))
        dose["carries_after"] = (dose.get("carries_before") or 0) + (dose.get("carry_count") or 0)
        ledger["carries_used"] = dose["carries_after"]
        carry.refresh_carry_ledger(ledger, bump=True)
        patient_of(dose)["carries_used"] = ledger.get("carries_used") or 0

    total, _ = inventory.dose_tariff_both(dose, order, program, patient_of(dose))
    dose["charge"] = total
    db.stamp(dose)
    program_svc.refresh_program(program, bump=True)
    return dose


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------
def complete(dose, body, actor):
    _ = actor
    # The only precondition completion declares is the state: priority 15's mass
    # balance and priority 17's witness rule both list the dispense, reschedule and
    # inventory-movement endpoints, not this one.
    if dose.get("status") != "DISPENSED":
        raise ApiError("ERR_DOSE_NOT_DISPENSED", "DoseDispense is not DISPENSED")
    patient = patient_of(dose)
    program = program_of(dose)

    for field in ("dispensed_mg", "wasted_mg", "returned_mg"):
        if field in body and body[field] is not None:
            dose[field] = r2(float(body[field]))

    dose["status"] = "COMPLETED"
    dose["completed_at"] = db.fmt_dt(db.clock_dt())

    if dose.get("source_type") == "TAKE_HOME_ISSUANCE":
        ledger = carry.ensure_ledger_for_patient(patient)
        carry.refresh_carry_ledger(ledger, bump=True)
        patient["carries_used"] = ledger.get("carries_used") or 0

    stability.refresh_patient(patient, publish="A")
    db.stamp(dose)
    db.stamp(patient)
    program_svc.refresh_program(program, bump=True)
    return dose


# ---------------------------------------------------------------------------
# refuse / cancel
# ---------------------------------------------------------------------------
def refuse(dose, actor):
    if dose.get("status") not in ("ARRIVED_AT_CLINIC", "NURSE_VERIFIED"):
        raise ApiError("ERR_DOSE_NOT_REFUSABLE", "DoseDispense is not refusable from its status")
    dose["status"] = "REFUSED"
    dose["completed_at"] = db.fmt_dt(db.clock_dt())
    db.stamp(dose)
    return dose


def cancel(dose, actor):
    if dose.get("status") not in DOSE_OPEN:
        raise ApiError("ERR_DOSE_NOT_CANCELLABLE", "DoseDispense is already in a terminal status")
    dose["status"] = "CANCELLED"
    dose["completed_at"] = db.fmt_dt(db.clock_dt())
    db.stamp(dose)
    if dose.get("privilege_id"):
        patient = patient_of(dose)
        if patient is not None:
            ledger = carry.ensure_ledger_for_patient(patient)
            carry.refresh_carry_ledger(ledger, bump=True)
            patient["carries_used"] = ledger.get("carries_used") or 0
    return dose


# ---------------------------------------------------------------------------
# reschedule
# ---------------------------------------------------------------------------
def reschedule(dose, body, actor):
    _ = actor
    if dose.get("status") in DOSE_TERMINAL:
        raise ApiError("ERR_DOSE_NOT_CANCELLABLE", "The dose is already in a terminal status")
    program = program_of(dose)
    new_moment = body.get("new_scheduled_datetime")
    if not new_moment:
        raise ApiError("ERR_INVALID_REQUEST", "new_scheduled_datetime is required")
    if body.get("executed_carries") is None:
        raise ApiError("ERR_INVALID_REQUEST", "executed_carries is required")
    if not body.get("schedule_id"):
        raise ApiError("ERR_INVALID_REQUEST", "schedule_id is required")
    check_clinic_day(
        program,
        dose.get("dose_date"),
        new_moment,
        dose.get("patient_id"),
        ignore_dose_id=dose["id"],
    )
    if program is not None:
        program_svc.ensure_not_frozen(program)
    # The cumulative movement may never exceed the frozen ordered milligrams.
    prior = (
        (dose.get("dispensed_mg") or 0.0)
        + (dose.get("wasted_mg") or 0.0)
        + (dose.get("returned_mg") or 0.0)
    )
    if r2(prior) > r2(dose.get("ordered_mg") or 0.0):
        raise ApiError("ERR_PARTIAL_EXCEEDS_ORDERED", "The cumulative movement exceeds ordered_mg")
    dose["scheduled_datetime"] = new_moment
    dose["executed_carries"] = int(body.get("executed_carries") or 0)
    dose["schedule_id"] = body.get("schedule_id")
    # The tariff is recomputed with the reschedule surcharge applied.
    order = order_of(dose)
    if order is not None:
        dose["reschedule_surcharge"] = 0.0
        dose["charge"] = inventory.dose_tariff(dose, order, program, patient_of(dose))
    db.stamp(dose)
    return dose


# ---------------------------------------------------------------------------
# missed doses
# ---------------------------------------------------------------------------
def apply_miss(dose, clock=None):
    """The full miss cascade (PRD 3.5 / SCAFFOLD DoseDispense -> MISSED)."""
    if clock is None:
        clock = db.clock_dt()
    dose["status"] = "MISSED"
    dose["completed_at"] = db.fmt_dt(clock)
    db.stamp(dose)

    patient = patient_of(dose)
    if patient is None:
        return dose

    patient_svc.refresh_denial_and_streak(patient, clock)
    stability.refresh_patient(patient, publish="B")

    # Recompute the look-ahead flag on every held privilege.
    dose_day = db.parse_date(dose.get("dose_date"))
    reconciled_through = db.parse_date(patient.get("journal_reconciled_through_date"))
    lookahead_day = (dose_day - timedelta(days=1)) if dose_day is not None else None
    if lookahead_day is not None:
        for row in db.take_home_privileges.values():
            if row.get("patient_id") != patient["id"]:
                continue
            if row.get("decision") != "PENDING_REVIEW":
                continue
            row["timetable_reconciled"] = bool(
                reconciled_through is not None and reconciled_through >= lookahead_day
            )
            db.touch_no_version(row)

    db.stamp(patient)
    if (patient.get("missed_dose_streak") or 0) >= 3 and patient.get("status") == "ACTIVE":
        from services.patient_flow import suspend_non_compliant

        suspend_non_compliant(patient)
    return dose


def sweep_missed_doses():
    """Automatic: a SCHEDULED dose whose dose_date has ended becomes MISSED."""
    clock = db.clock_dt()
    today = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    for row in list(db.dose_dispenses.values()):
        if row.get("status") != "SCHEDULED":
            continue
        dose_day = db.parse_date(row.get("dose_date"))
        if dose_day is None or clock.strftime("%Y-%m-%d") <= row.get("dose_date"):
            continue
        if today <= dose_day:
            continue
        patient = patient_of(row)
        if patient is None or patient.get("status") not in (
            "ADMITTED",
            "ACTIVE",
            "SUSPENDED_NON_COMPLIANT",
        ):
            continue
        apply_miss(row, clock)