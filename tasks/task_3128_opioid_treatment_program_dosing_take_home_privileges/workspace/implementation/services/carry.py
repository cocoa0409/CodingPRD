"""Carry quota, the cap waterfall and the milligram conservation identities.

Implements PRD 2.7 (§carry quota and conservation), PRD 3.6/3.7/3.9 and
SCAFFOLD calculations carry_cap_waterfall and phase_stability_exception_cap.
"""
from datetime import timedelta

import db
from constants import (
    CARRY_PHASE_TABLE,
    CARRY_TIME_IN_TREATMENT_TABLE,
    DOSE_OPEN,
    POOL_DIVISOR,
    PRIVILEGE_GRANTED,
)
from errors import ApiError
from services.num import r2


# ---------------------------------------------------------------------------
# Carry tables
# ---------------------------------------------------------------------------
def table_cap_time(days):
    """Walk the time-in-treatment table in descending threshold order."""
    for threshold, cap in CARRY_TIME_IN_TREATMENT_TABLE:
        if days >= threshold:
            return cap
    return 0


def table_cap_phase(phase):
    return CARRY_PHASE_TABLE.get(phase, 0)


# ---------------------------------------------------------------------------
# CarryQuotaLedger
# ---------------------------------------------------------------------------
def quota_for_program(program_id):
    for ledger in db.carry_quota_ledgers.values():
        if ledger.get("program_id") == program_id:
            return ledger
    return None


class _NullLedger(dict):
    """A no-op ledger used when the program has no carry quota row open."""

    def __setitem__(self, key, value):
        return None

    def setdefault(self, key, default=None):
        return default


NULL_LEDGER = _NullLedger()


def compute_granted_carries(program_id):
    """Sum of approved_carries over privileges with decision APPROVED* ."""
    total = 0
    for row in db.take_home_privileges.values():
        if row.get("program_id") != program_id:
            continue
        if row.get("decision") in PRIVILEGE_GRANTED:
            total += row.get("approved_carries") or 0
    return total


def compute_held_privilege_count(program_id):
    return sum(
        1
        for row in db.take_home_privileges.values()
        if row.get("program_id") == program_id and row.get("decision") == "PENDING_REVIEW"
    )


def refresh_quota(ledger, bump=False):
    """available_carries := allotted_carries - granted_carries (identity C1)."""
    program_id = ledger.get("program_id")
    ledger["granted_carries"] = compute_granted_carries(program_id)
    ledger["available_carries"] = (ledger.get("allotted_carries") or 0) - ledger["granted_carries"]
    ledger["held_privilege_count"] = compute_held_privilege_count(program_id)
    if bump:
        db.stamp(ledger)
    return ledger


def program_pool_remaining(program_id):
    ledger = quota_for_program(program_id)
    if ledger is None:
        raise ApiError(
            "ERR_CARRY_LEDGER_NOT_FOUND",
            "No carry quota ledger exists for this program",
        )
    return (ledger.get("allotted_carries") or 0) - compute_granted_carries(program_id)


def pool_cap(program_id):
    """max(0, floor(available_carries / 2.0)) — never fully drainable by one patient."""
    remaining = program_pool_remaining(program_id)
    halved = remaining / POOL_DIVISOR
    floored = int(halved // 1)
    return floored if floored > 0 else 0


# ---------------------------------------------------------------------------
# The two cap calculations
# ---------------------------------------------------------------------------
def carry_cap_waterfall(privilege, patient, program_id):
    """min(requested_carries, table_cap, pool_cap) for the ordinary evaluation path."""
    table_cap = table_cap_time(patient.get("time_in_treatment_days") or 0)
    pool = pool_cap(program_id)
    return min(
        privilege.get("requested_carries") or 0,
        table_cap,
        pool,
    )


def phase_stability_exception_cap(exception, patient, program_id):
    """min(requested, max(phase_cap, time_cap), pool_cap) for the exception path."""
    time_cap = table_cap_time(patient.get("time_in_treatment_days") or 0)
    phase_cap = table_cap_phase(patient.get("treatment_phase"))
    pool = pool_cap(program_id)
    return min(
        exception.get("requested_carries") or 0,
        max(phase_cap, time_cap),
        pool,
    )


# ---------------------------------------------------------------------------
# TakeHomeCarryLedger
# ---------------------------------------------------------------------------
def ledger_for_patient(patient_id):
    for ledger in db.take_home_carry_ledgers.values():
        if ledger.get("patient_id") == patient_id:
            return ledger
    return None


def ensure_ledger_for_patient(patient):
    ledger = ledger_for_patient(patient["id"])
    if ledger is None:
        from services import entity

        ledger = entity.make_take_home_carry_ledger(patient)
        db.take_home_carry_ledgers[ledger["id"]] = ledger
    return ledger


def refresh_carry_ledger(ledger, bump=False):
    """Recompute every derived quantity on the patient-level carry ledger."""
    patient_id = ledger.get("patient_id")

    owns = 0
    charges_held = 0
    pending = 0
    for row in db.take_home_privileges.values():
        if row.get("patient_id") != patient_id:
            continue
        if row.get("decision") in PRIVILEGE_GRANTED:
            owns += 1
        elif row.get("decision") == "PENDING_REVIEW":
            pending += 1
            charges_held += row.get("hold_ledger_delta") or 0
    ledger["owns_privilege_count"] = owns
    ledger["charges_held"] = charges_held
    # Count of appended outstanding holds awaiting a system posting: a privilege
    # opened on hold appends one, and approval/denial/revocation releases it.
    ledger["carries_held"] = pending

    # carried_issued_mg: sum of ordered_mg over take-home dose rows ever created.
    issued = 0.0
    dispensed = 0.0
    consumed = 0.0
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id:
            continue
        if row.get("source_type") != "TAKE_HOME_ISSUANCE":
            continue
        issued += row.get("ordered_mg") or 0.0
        if row.get("status") == "COMPLETED":
            dispensed += row.get("dispensed_mg") or 0.0
            consumed += (row.get("wasted_mg") or 0.0) + (row.get("returned_mg") or 0.0)
    ledger["carried_issued_mg"] = r2(issued)
    ledger["carried_dispensed_mg"] = r2(dispensed)
    ledger["carried_consumed_mg"] = r2(consumed)
    ledger["carried_voided_mg"] = r2(ledger.get("carried_voided_mg") or 0.0)
    ledger["carried_balance_mg"] = r2(
        ledger["carried_issued_mg"]
        - ledger["carried_voided_mg"]
        - ledger["carried_dispensed_mg"]
        - ledger["carried_consumed_mg"]
    )

    # carries_used: the carry_count of every take-home dose row not cancelled by a
    # revocation — "sum of privilege carries consumed, minus carries restored by
    # revocation".
    used = 0
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id:
            continue
        if not row.get("privilege_id"):
            continue
        if row.get("status") == "CANCELLED":
            continue
        used += row.get("carry_count") or 0
    ledger["carries_used"] = used if used > 0 else 0
    ledger["carry_variance"] = 0
    if bump:
        db.stamp(ledger)
    return ledger


def void_carried_mg(ledger, doses):
    """Accumulate ordered_mg for take-home rows voided by a revocation (idempotent)."""
    counted = ledger.setdefault("_voided_dose_ids", [])
    added = 0.0
    for row in doses:
        if row["id"] in counted:
            continue
        counted.append(row["id"])
        added += row.get("ordered_mg") or 0.0
    if added:
        ledger["carried_voided_mg"] = r2((ledger.get("carried_voided_mg") or 0.0) + added)
    return ledger["carried_voided_mg"]


def refresh_patient_carries(patient, bump=False):
    ledger = ensure_ledger_for_patient(patient)
    refresh_carry_ledger(ledger, bump=bump)
    patient["carries_used"] = ledger.get("carries_used") or 0
    return ledger


def refresh_all_quota_ledgers(bump=False):
    for ledger in db.carry_quota_ledgers.values():
        refresh_quota(ledger, bump=bump)


def refresh_quota_tolerant(program_id, bump=True):
    """Refresh the program pool when a ledger exists; otherwise do nothing."""
    ledger = quota_for_program(program_id)
    if ledger is None:
        return None
    return refresh_quota(ledger, bump=bump)


def release_carries(program_id, freed):
    """On revocation: granted_carries -= freed_carries and released_carries += freed.

    released_carries is a reporting field only and is never added back into the
    pool, because availability is defined as allotted_carries - granted_carries.
    """
    ledger = quota_for_program(program_id)
    if ledger is None:
        return None
    ledger["granted_carries"] = compute_granted_carries(program_id)
    ledger["released_carries"] = (ledger.get("released_carries") or 0) + freed
    ledger["available_carries"] = (ledger.get("allotted_carries") or 0) - ledger["granted_carries"]
    ledger["held_privilege_count"] = compute_held_privilege_count(program_id)
    db.stamp(ledger)
    return ledger


# ---------------------------------------------------------------------------
# Take-home dose synthesis
# ---------------------------------------------------------------------------
def active_order_for_patient(patient_id):
    for row in db.dose_orders.values():
        if row.get("patient_id") == patient_id and row.get("status") == "ACTIVE":
            return row
    return None


def synthesize_take_home_doses(patient, privilege, count):
    """Synthesize one TAKE_HOME_ISSUANCE row per open day, ordered_mg from the order.

    These are appointment rows on the patient's dispensing calendar; they hold no
    hold of their own at the carry ledger and are waiting for the patient's
    arrival, not for a system posting.
    """
    from services import entity

    order = active_order_for_patient(patient["id"])
    ordered_mg = (order or {}).get("ordered_daily_mg") or 0.0
    program = db.programs.get(patient.get("program_id"))
    created = []
    if program is None or count <= 0:
        return created
    for delta in _open_day_offsets(program, count):
        dose_date = (db.clock_dt() + timedelta(days=delta)).strftime("%Y-%m-%d")
        scheduled = _scheduled_instant(program, delta)
        row = entity.make_dose_dispense(
            order=order,
            patient=patient,
            dose_date=dose_date,
            scheduled_datetime=scheduled,
            source_type="TAKE_HOME_ISSUANCE",
            privilege_id=privilege["id"],
            carry_count=1,
        )
        row["ordered_mg"] = r2(ordered_mg)
        db.dose_dispenses[row["id"]] = row
        created.append(row)
    if created:
        ledger = ensure_ledger_for_patient(patient)
        refresh_carry_ledger(ledger, bump=True)
    return created


def _open_day_offsets(program, count):
    open_days = set(program.get("open_days") or [])
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    if not open_days:
        open_days = set(codes)
    out = []
    delta = 1
    while len(out) < count and delta < 400:
        if codes[(db.clock_dt() + timedelta(days=delta)).weekday()] in open_days:
            out.append(delta)
        delta += 1
    return out


def _scheduled_instant(program, delta):
    start = program.get("clinic_hours_start") or "08:00"
    moment = (db.clock_dt() + timedelta(days=delta)).replace(
        hour=int(start.split(":")[0]), minute=int(start.split(":")[1]), second=0, microsecond=0
    )
    return db.fmt_dt(moment)