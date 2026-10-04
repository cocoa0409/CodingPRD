"""The two stability channels (PRD 2.5, SCAFFOLD calculations R2a / R2b)."""
from datetime import timedelta

import db
from constants import (
    COUNSELING_CAP,
    COUNSELING_WEIGHT,
    DENIAL_WEIGHT,
    DOSE_COMPLETION_WEIGHT,
    LOOKBACK_FIRST_ENTRY_MG,
    LOOKBACK_LAST_ENTRY_MG,
    MISSED_STREAK_LINEAR,
    MISSED_STREAK_QUADRATIC,
    READINESS_CONFIRMED_DIVERSION_PENALTY,
    READINESS_COUNSELING_DEFICIENT_PENALTY,
    READINESS_MISSED_STREAK_WEIGHT,
    READINESS_NO_TRANSPORT_PENALTY,
    READINESS_REVIEW_OVERDUE_PENALTY,
    READINESS_UNDER_INVESTIGATION_PENALTY,
    STABILITY_BASE,
    STABILITY_FLOOR_MAINTENANCE,
    STABILITY_FLOOR_OTHER,
    TREATMENT_DAYS_CAP,
    TREATMENT_DAYS_WEIGHT,
)
from services.num import r1_clamped


def _completed_doses_28d(patient_id, clock):
    window_start = clock - timedelta(days=28)
    count = 0
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id or row.get("status") != "COMPLETED":
            continue
        completed = db.parse_iso(row.get("completed_at"))
        if completed is None:
            continue
        if window_start <= completed <= clock:
            count += 1
    return count


def _completed_counseling_28d(patient_id, clock):
    window_start = clock - timedelta(days=28)
    count = 0
    for row in db.counseling_sessions.values():
        if row.get("patient_id") != patient_id or row.get("status") != "COMPLETED":
            continue
        completed = db.parse_iso(row.get("completed_at"))
        if completed is None:
            continue
        if window_start <= completed <= clock:
            count += 1
    return count


def missed_penalty(streak):
    """0.0 when s <= 0; otherwise 3.0*s + 0.5*s*(s-1)/2 for s >= 1."""
    if streak <= 0:
        return 0.0
    return MISSED_STREAK_LINEAR * streak + MISSED_STREAK_QUADRATIC * streak * (streak - 1) / 2.0


def direction_a(patient, clock=None):
    """DIRECTION_A_STABILITY: the published reading on every patient read."""
    if clock is None:
        clock = db.clock_dt()
    days = patient.get("time_in_treatment_days") or 0
    score = STABILITY_BASE
    score += min(TREATMENT_DAYS_CAP, TREATMENT_DAYS_WEIGHT * days)
    score += DOSE_COMPLETION_WEIGHT * _completed_doses_28d(patient["id"], clock)
    score -= missed_penalty(patient.get("missed_dose_streak") or 0)
    score -= DENIAL_WEIGHT * (patient.get("denial_count_12mo") or 0)
    score += COUNSELING_WEIGHT * min(COUNSELING_CAP, _completed_counseling_28d(patient["id"], clock))
    return r1_clamped(score)


def _journal_window(patient_id, clock):
    """The patient's dose journal window: DoseDispense rows for the last 28 days."""
    window_start = clock - timedelta(days=28)
    rows = []
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id:
            continue
        created = db.parse_iso(row.get("created_at"))
        if created is None:
            continue
        if window_start <= created <= clock:
            rows.append(row)
    rows.sort(key=lambda r: (str(r.get("created_at", "")), str(r.get("id", ""))))
    return rows


def direction_b(patient, clock=None):
    """DIRECTION_B_TAKE_HOME_READINESS: gates carries, never published on a read."""
    if clock is None:
        clock = db.clock_dt()
    base = direction_a(patient, clock)
    readiness = base
    readiness -= READINESS_MISSED_STREAK_WEIGHT * (patient.get("missed_dose_streak") or 0)
    if patient.get("transportation_type") == "NO_RELIABLE_TRANSPORT":
        readiness -= READINESS_NO_TRANSPORT_PENALTY
    standing = patient.get("diversion_standing")
    if standing == "CONFIRMED_DIVERSION":
        readiness -= READINESS_CONFIRMED_DIVERSION_PENALTY
    elif standing == "UNDER_INVESTIGATION":
        readiness -= READINESS_UNDER_INVESTIGATION_PENALTY
    counseling = patient.get("counseling_standing")
    if counseling == "COUNSELING_DEFICIENT":
        readiness -= READINESS_COUNSELING_DEFICIENT_PENALTY
    elif counseling == "REVIEW_OVERDUE":
        readiness -= READINESS_REVIEW_OVERDUE_PENALTY
    ready = r1_clamped(readiness)

    # Journal look-back discount: the earliest window entry costs 2.0 and the
    # latest costs 1.5; with fewer than two entries only those present are charged.
    entries = _journal_window(patient["id"], clock)
    discount = 0.0
    if len(entries) >= 1:
        discount += LOOKBACK_FIRST_ENTRY_MG
    if len(entries) >= 2:
        discount += LOOKBACK_LAST_ENTRY_MG
    ready = r1_clamped(ready - discount)
    return ready


def floor_for(patient):
    """The phase-dependent stability floor (70.0 in MAINTENANCE, else 75.0)."""
    if patient.get("treatment_phase") == "MAINTENANCE":
        return STABILITY_FLOOR_MAINTENANCE
    return STABILITY_FLOOR_OTHER


def cleared(patient, clock=None):
    return direction_b(patient, clock) >= floor_for(patient)


def refresh_patient(patient, publish=None, clock=None):
    """Recompute the published reading and optionally mirror it into stability_posting.

    `publish` names the channel whose value is copied into stability_posting
    ("A" or "B"); patient reads publish direction A per PRD 3.14 / 2.5.
    """
    if clock is None:
        clock = db.clock_dt()
    value_a = direction_a(patient, clock)
    value_b = direction_b(patient, clock)
    patient["stability_score"] = value_a
    if publish == "A":
        patient["stability_posting"] = value_a
    elif publish == "B":
        patient["stability_posting"] = value_b
    return value_a, value_b