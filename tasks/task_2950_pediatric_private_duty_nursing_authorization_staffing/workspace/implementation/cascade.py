"""Cascades (PRD 2.10, 3.2, 3.8, 3.9) and derived-field recomputation bookkeeping.

PRD 2.4: recomputing a derived field counts as a mutation of the row that owns
it. A request snapshots every derived signature before it mutates anything and,
just before responding, bumps updated_at / version on each row whose derived
values actually moved and that the handler did not already touch itself.
"""
from flask import g

import derive
import envelope
import store
from store import db
from timeutil import add_days, week_start

FUTURE_CANCELLABLE = ("OPEN", "ASSIGNED", "ESCALATED")


# --------------------------------------------------------------------------- #
# recomputation bookkeeping
# --------------------------------------------------------------------------- #
def _sig_nurse(row):
    return (
        derive.nurse_scheduled_minutes_this_week(row["id"]),
        tuple(derive.verified_skills(row["id"])),
    )


def _sig_auth(row):
    return derive.auth_week_hours(row)


def _sig_case(row):
    fill_rate, unfilled = derive.case_fill_metrics(row)
    return (
        fill_rate,
        unfilled,
        derive.case_billed_units(row),
        derive.supervisory_due_at(row),
        derive.supervisory_status(row),
    )


_WATCHED = (
    ("nurses", _sig_nurse),
    ("authorizations", _sig_auth),
    ("cases", _sig_case),
)


def begin():
    snapshot = {}
    for table_name, sig in _WATCHED:
        for row in getattr(db, table_name).values():
            snapshot[row["id"]] = (table_name, sig(row))
    g.pdn_snapshot = snapshot
    g.pdn_touched = set()


def touch(row):
    """Explicitly mutate a row: refresh updated_at and increment version once."""
    if row is None:
        return
    store.touch(row)
    touched = getattr(g, "pdn_touched", None)
    if touched is not None:
        touched.add(row["id"])


def finish():
    snapshot = getattr(g, "pdn_snapshot", None)
    if snapshot is None:
        return
    touched = getattr(g, "pdn_touched", set())
    for row_id, (table_name, old_sig) in snapshot.items():
        if row_id in touched:
            continue
        row = getattr(db, table_name).get(row_id)
        if row is None:
            continue
        new_sig = dict(_WATCHED)[table_name](row)
        if new_sig != old_sig:
            store.touch(row)
            touched.add(row_id)


def respond(serializer, row, status=200):
    finish()
    return envelope.ok(serializer(row), status)


def respond_data(data, status=200):
    finish()
    return envelope.ok(data, status)


# --------------------------------------------------------------------------- #
# shift / assignment cancellation
# --------------------------------------------------------------------------- #
def cancel_assignment(assignment, reason):
    assignment["status"] = "CANCELLED"
    assignment["cancel_reason"] = reason
    touch(assignment)


def cancel_shift(shift, reason):
    shift["staffing_status"] = "CANCELLED"
    shift["cancel_reason"] = reason
    touch(shift)
    active = derive.active_assignment_of_shift(shift["id"])
    if active is not None:
        cancel_assignment(active, reason)


def cancel_future_shifts_of_case(case, shift_reason, statuses=FUTURE_CANCELLABLE):
    """Only the future is disturbed: start_at at or after the logical clock."""
    count = 0
    for shift in derive.shifts_of_case(case["id"]):
        if shift["staffing_status"] not in statuses:
            continue
        if shift["start_at"] < db.clock:
            continue
        cancel_shift(shift, shift_reason)
        count += 1
    return count


def hold_case(case, hold_reason, incident_report_id=None, shift_reason="CASE_HOLD"):
    case["status"] = "ON_HOLD"
    case["hold_reason"] = hold_reason
    case["hold_incident_report_id"] = incident_report_id
    touch(case)
    cancel_future_shifts_of_case(case, shift_reason)


# --------------------------------------------------------------------------- #
# authorization reduction trim (PRD 3.9)
# --------------------------------------------------------------------------- #
def trim_cascade(auth):
    """Cancel surplus future ASSIGNED shifts until each week fits the new cap."""
    target_minutes = int(derive.dec(auth["approved_hours_per_week"]) * derive.dec(60))
    case_ids = derive.case_ids_of_auth(auth["id"])
    week = week_start(db.clock)
    while week < auth["effective_end"]:
        window = (week, add_days(week, 7))
        while True:
            committed = 0
            for shift in db.shifts.values():
                if shift["case_id"] not in case_ids:
                    continue
                if shift["staffing_status"] not in ("ASSIGNED", "COMPLETED"):
                    continue
                if window[0] <= shift["start_at"] < window[1]:
                    committed += shift["scheduled_minutes"]
            if committed <= target_minutes:
                break
            candidates = []
            for shift in db.shifts.values():
                if shift["case_id"] not in case_ids:
                    continue
                if shift["staffing_status"] != "ASSIGNED":
                    continue
                if shift["start_at"] < db.clock:
                    continue
                if window[0] <= shift["start_at"] < window[1]:
                    candidates.append(shift)
            if not candidates:
                break
            candidates.sort(key=lambda s: (s["start_at"], s["created_at"]))
            cancel_shift(candidates[-1], "AUTH_REDUCTION")
        week = add_days(week, 7)


# --------------------------------------------------------------------------- #
# competency revocation (PRD 3.2)
# --------------------------------------------------------------------------- #
def competency_revocation_cascade(nurse_id, skill):
    for assignment in list(db.assignments.values()):
        if assignment["nurse_id"] != nurse_id or assignment["status"] != "ACTIVE":
            continue
        shift = db.shifts.get(assignment["shift_id"])
        if shift is None or shift["start_at"] < db.clock:
            continue
        if skill not in shift["required_skills"]:
            continue
        cancel_shift(shift, "COMPETENCY_REVOKED")


# --------------------------------------------------------------------------- #
# nurse leaving ACTIVE (PRD 3.1)
# --------------------------------------------------------------------------- #
def nurse_left_active_cascade(nurse_id):
    """Assignments on not-yet-started visits are released; the shift reopens."""
    for assignment in list(db.assignments.values()):
        if assignment["nurse_id"] != nurse_id or assignment["status"] != "ACTIVE":
            continue
        shift = db.shifts.get(assignment["shift_id"])
        if shift is None or shift["evv_status"] != "NOT_STARTED":
            continue
        cancel_assignment(assignment, "SCHEDULER")
        shift["staffing_status"] = "OPEN"
        touch(shift)


# --------------------------------------------------------------------------- #
# authorization expiry (PRD 3.9) -- driven by the daily checkpoint
# --------------------------------------------------------------------------- #
def authorization_expiry_cascade(auth):
    auth["status"] = "EXPIRED"
    touch(auth)
    for case in list(db.cases.values()):
        if case["authorization_id"] != auth["id"]:
            continue
        if case["status"] not in ("PENDING_STAFFING", "ACTIVE"):
            continue
        hold_case(case, "AUTHORIZATION_EXPIRED", None, "AUTH_EXPIRY")


# --------------------------------------------------------------------------- #
# case closure (PRD 3.4)
# --------------------------------------------------------------------------- #
def close_case_cascade(case):
    cancel_future_shifts_of_case(case, "SCHEDULER")
    patient = db.patients.get(case["patient_id"])
    if patient is None:
        return
    cases = [c for c in db.cases.values() if c["patient_id"] == patient["id"]]
    if cases and all(c["status"] == "CLOSED" for c in cases):
        if patient["status"] != "DISCHARGED":
            patient["status"] = "DISCHARGED"
            touch(patient)
