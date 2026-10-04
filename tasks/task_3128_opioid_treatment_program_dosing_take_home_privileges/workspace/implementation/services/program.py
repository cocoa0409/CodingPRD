"""Program posture ladder, counters and suspension sweeps (PRD 2.6, 3.10, 3.13)."""
import db
from constants import DOSE_OPEN, PRIVILEGE_GRANTED, RESTRICTED_VARIANCE_MG
from errors import ApiError
from services.num import r2

OPEN_CASE_STATUSES = ("OPEN", "UNDER_REVIEW")


def open_diversion_case_count(program_id):
    return sum(
        1
        for row in db.diversion_cases.values()
        if row.get("program_id") == program_id and row.get("status") in OPEN_CASE_STATUSES
    )


def open_critical_finding_count(program_id):
    return sum(
        1
        for row in db.corrective_actions.values()
        if row.get("program_id") == program_id
        and row.get("severity") == "CRITICAL"
        and row.get("status") == "OPEN"
    )


def pending_waste_mg(program_id):
    total = 0.0
    for row in db.inventory_transactions.values():
        if row.get("program_id") != program_id:
            continue
        if row.get("transaction_type") != "WASTE" or row.get("status") != "RECORDED":
            continue
        total += abs(row.get("quantity_mg") or 0.0)
    return r2(total)


def compute_posture(program):
    """The five-branch ladder, evaluated in order; the first match wins."""
    if program.get("status") == "SUSPENDED":
        return "FROZEN", "PROGRAM_SUSPENDED_BY_REGULATOR"
    if (program.get("open_diversion_case_count") or 0) >= 1:
        return "RESTRICTED", "DIVERSION_CASE_OPEN"
    if (program.get("open_critical_finding_count") or 0) >= 1:
        return "RESTRICTED", "CRITICAL_CORRECTIVE_ACTION_OPEN"
    if (program.get("latest_inventory_variance_mg") or 0.0) > RESTRICTED_VARIANCE_MG:
        return "RESTRICTED", "INVENTORY_VARIANCE_OVER_THRESHOLD"
    return "NORMAL", None


def refresh_program(program, bump=False):
    """Recompute the computed counters and then the posture. A change is a mutation."""
    before = (
        program.get("open_diversion_case_count"),
        program.get("open_critical_finding_count"),
        program.get("pending_waste_mg"),
        program.get("posture"),
        program.get("posture_reason_code"),
    )
    program["open_diversion_case_count"] = open_diversion_case_count(program["id"])
    program["open_critical_finding_count"] = open_critical_finding_count(program["id"])
    program["pending_waste_mg"] = pending_waste_mg(program["id"])
    program["latest_inventory_variance_mg"] = r2(program.get("latest_inventory_variance_mg") or 0.0)
    program["cumulative_write_off_mg"] = r2(program.get("cumulative_write_off_mg") or 0.0)
    if program["cumulative_write_off_mg"] < 0.0:
        program["cumulative_write_off_mg"] = 0.0
    posture, reason = compute_posture(program)
    program["posture"] = posture
    program["posture_reason_code"] = reason
    changed = before != (
        program["open_diversion_case_count"],
        program["open_critical_finding_count"],
        program["pending_waste_mg"],
        program["posture"],
        program["posture_reason_code"],
    )
    if bump and changed:
        db.stamp(program)
    elif bump:
        db.touch_no_version(program)
    return program


def refresh_program_by_id(program_id, bump=True):
    program = db.programs.get(program_id)
    if program is None:
        return None
    return refresh_program(program, bump=bump)


def refresh_all_programs(bump=False):
    for program in list(db.programs.values()):
        refresh_program(program, bump=False)
    return None


# ---------------------------------------------------------------------------
# Posture gates
# ---------------------------------------------------------------------------
def _program_of(resource):
    return db.programs.get(resource.get("program_id"))


def ensure_not_frozen(program):
    """Priority 8: must not be FROZEN (dispense/defer/schedule/grant operations)."""
    if program is None:
        return
    if program.get("posture") == "FROZEN":
        raise ApiError(
            "ERR_PROGRAM_OPERATIONALLY_BLOCKED",
            "Program posture is FROZEN",
        )


def ensure_normal_for_medication(program):
    """Priority 8 for the operations that require NORMAL rather than non-FROZEN."""
    if program is None:
        return
    if program.get("posture") != "NORMAL":
        raise ApiError(
            "ERR_PROGRAM_OPERATIONALLY_BLOCKED",
            "Program posture is not NORMAL",
        )


def ensure_carry_posture(program):
    """Priority 9: carries need NORMAL — RESTRICTED is forbidden outright."""
    if program is None:
        return
    if program.get("posture") != "NORMAL":
        raise ApiError(
            "ERR_PROGRAM_POSTURE_RESTRICTED",
            "Program posture is RESTRICTED",
        )


# ---------------------------------------------------------------------------
# Program suspension sweeps
# ---------------------------------------------------------------------------
def suspend_program(program, actor):
    if program.get("status") == "SUSPENDED":
        raise ApiError("ERR_PROGRAM_ALREADY_SUSPENDED", "Program is already SUSPENDED")
    program["status"] = "SUSPENDED"

    # Every open dose is cancelled.
    from services import carry
    for row in db.dose_dispenses.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("status") in DOSE_OPEN:
            row["status"] = "CANCELLED"
            row["completed_at"] = db.fmt_dt(db.clock_dt())
            db.stamp(row)

    # Every held privilege whose timetable is reconciled becomes DENIED.
    for row in db.take_home_privileges.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("decision") == "PENDING_REVIEW" and row.get("timetable_reconciled"):
            row["decision"] = "DENIED"
            row["denial_reason_code"] = "PROGRAM_POSTURE_RESTRICTED"
            row["hold_ledger_delta"] = 0
            db.stamp(row)

    # Every guest arrangement receiving at this program is cancelled.
    for row in db.guest_dosing_arrangements.values():
        if row.get("receiving_program_id") != program["id"]:
            continue
        if row.get("status") in ("PENDING_RECEIVING_ACK", "ACTIVE"):
            row["status"] = "CANCELLED"
            db.stamp(row)

    for ledger in db.take_home_carry_ledgers.values():
        carry.refresh_carry_ledger(ledger, bump=False)
    from services.carry import refresh_all_quota_ledgers

    refresh_all_quota_ledgers()
    refresh_program(program, bump=True)
    return program


def resume_program(program, actor):
    if program.get("status") != "SUSPENDED":
        raise ApiError("ERR_PROGRAM_NOT_SUSPENDED", "Program is not SUSPENDED")
    program["status"] = "ACTIVE"
    program["posture"] = "NORMAL"
    program["posture_reason_code"] = None
    # The ladder runs immediately against the program's current facts.
    refresh_program(program, bump=True)
    return program