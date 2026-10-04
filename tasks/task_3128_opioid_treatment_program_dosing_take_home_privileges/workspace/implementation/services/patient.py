"""Patient derivations: time in treatment, risk tier, counseling standing (PRD 3.2, 3.8)."""
from datetime import timedelta

import db
from constants import (
    DIVERSION_POINTS,
    PHASE_CADENCE,
    REVIEW_GRACE_DAYS,
    RISK_DENIAL_CAP,
    RISK_DENIAL_WEIGHT,
    RISK_HIGH_THRESHOLD,
    RISK_MODERATE_THRESHOLD,
    RISK_PHASE_DECAY_BASE,
    RISK_PHASE_DECAY_RATE,
    RISK_STREAK_WEIGHT,
    TRANSPORT_POINTS,
)
from services.num import r1


def derive_time_in_treatment(patient, clock=None):
    """Whole days from admission_datetime to the logical clock, floor-rounded."""
    if clock is None:
        clock = db.clock_dt()
    admission = db.parse_iso(patient.get("admission_datetime"))
    if admission is None:
        patient["time_in_treatment_days"] = 0
        return 0
    days = int((clock - admission) // timedelta(days=1))
    if days < 0:
        days = 0
    patient["time_in_treatment_days"] = days
    return days


def transport_points(patient):
    return TRANSPORT_POINTS.get(patient.get("transportation_type"), 0.0)


def diversion_points(patient):
    return DIVERSION_POINTS.get(patient.get("diversion_standing"), 0.0)


def compute_risk_score(patient, clock=None):
    if clock is None:
        clock = db.clock_dt()
    derive_time_in_treatment(patient, clock)
    denial = patient.get("denial_count_12mo") or 0
    streak = patient.get("missed_dose_streak") or 0
    days = patient.get("time_in_treatment_days") or 0
    score = transport_points(patient)
    score += diversion_points(patient)
    score += RISK_DENIAL_WEIGHT * min(RISK_DENIAL_CAP, denial)
    score += RISK_STREAK_WEIGHT * streak
    score += max(0.0, RISK_PHASE_DECAY_BASE - RISK_PHASE_DECAY_RATE * days)
    return r1(score)


def cut_tier(score):
    if score >= RISK_HIGH_THRESHOLD:
        return "HIGH"
    if score >= RISK_MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


def refresh_risk(patient, clock=None):
    score = compute_risk_score(patient, clock)
    patient["risk_score_points"] = score
    patient["risk_tier"] = cut_tier(score)
    return score


def compute_denial_count_12mo(patient_id, clock=None):
    """MISSED rows in the trailing 365 days at the logical clock."""
    if clock is None:
        clock = db.clock_dt()
    window_start = clock - timedelta(days=365)
    count = 0
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient_id or row.get("status") != "MISSED":
            continue
        created = db.parse_iso(row.get("created_at"))
        if created is None or created < window_start or created > clock:
            continue
        count += 1
    return count


def compute_missed_streak(patient_id):
    """Consecutive MISSED rows with no intervening COMPLETED row, oldest first."""
    rows = [r for r in db.dose_dispenses.values() if r.get("patient_id") == patient_id]
    rows.sort(key=lambda r: (str(r.get("created_at", "")), str(r.get("id", ""))))
    streak = 0
    for row in rows:
        status = row.get("status")
        if status == "COMPLETED":
            streak = 0
        elif status == "MISSED":
            streak += 1
    return streak


def refresh_denial_and_streak(patient, clock=None):
    if clock is None:
        clock = db.clock_dt()
    patient["denial_count_12mo"] = compute_denial_count_12mo(patient["id"], clock)
    patient["missed_dose_streak"] = compute_missed_streak(patient["id"])
    return patient["denial_count_12mo"], patient["missed_dose_streak"]


def _completed_minutes_in_window(patient_id, window_start, clock):
    total = 0
    for row in db.counseling_sessions.values():
        if row.get("patient_id") != patient_id or row.get("status") != "COMPLETED":
            continue
        completed = db.parse_iso(row.get("completed_at"))
        if completed is None:
            continue
        if window_start <= completed <= clock:
            total += row.get("attended_minutes") or 0
    return total


def _latest_completed_review(patient_id):
    rows = [
        r
        for r in db.treatment_plan_reviews.values()
        if r.get("patient_id") == patient_id and r.get("status") == "COMPLETED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (str(r.get("reviewed_at", "")), str(r.get("created_at", ""))))
    return rows[-1]


def compute_counseling_standing(patient, clock=None):
    """Merge the counseling reading and the plan-review reading, most severe wins."""
    if clock is None:
        clock = db.clock_dt()
    cadence = PHASE_CADENCE.get(patient.get("treatment_phase"), 7)
    window_start = clock - timedelta(days=cadence)
    credited = _completed_minutes_in_window(patient["id"], window_start, clock)
    counseling_standing = "CURRENT" if credited >= 60.0 else "COUNSELING_DEFICIENT"

    review = _latest_completed_review(patient["id"])
    if review is None:
        admission = db.parse_iso(patient.get("admission_datetime"))
        if admission is None:
            review_standing = "REVIEW_OVERDUE"
        elif clock > admission + timedelta(days=REVIEW_GRACE_DAYS):
            review_standing = "COUNSELING_DEFICIENT"
        else:
            review_standing = "REVIEW_OVERDUE"
    else:
        due = db.parse_iso(review.get("next_due_at"))
        if due is None:
            review_standing = "CURRENT"
        elif clock < due:
            review_standing = "CURRENT"
        elif clock < due + timedelta(days=REVIEW_GRACE_DAYS):
            review_standing = "REVIEW_OVERDUE"
        else:
            review_standing = "COUNSELING_DEFICIENT"

    severity = {"CURRENT": 0, "REVIEW_OVERDUE": 1, "COUNSELING_DEFICIENT": 2}
    if severity[review_standing] > severity[counseling_standing]:
        return review_standing
    return counseling_standing


def refresh_counseling(patient, clock=None):
    standing = compute_counseling_standing(patient, clock)
    patient["counseling_standing"] = standing
    return standing


def min_open_day_delta(patient, program, clock=None):
    """Smallest whole-day offset that lands on one of the program's open days."""
    if clock is None:
        clock = db.clock_dt()
    open_days = set(program.get("open_days") or [])
    if not open_days:
        return 1
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    delta = 1
    while delta <= 14:
        if codes[(clock + timedelta(days=delta)).weekday()] in open_days:
            return delta
        delta += 1
    return 1


def working_weekdays(program, start_delta, count):
    """The first `count` open-day instants (as ISO dates) on or after start_delta.

    The granted carries are issued on the first N open days after the evaluation.
    """
    open_days = set(program.get("open_days") or [])
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    if not open_days:
        open_days = set(codes)
    out = []
    delta = start_delta
    limit = start_delta + 400
    while len(out) < count and delta <= limit:
        if codes[(db.clock_dt() + timedelta(days=delta)).weekday()] not in open_days:
            delta += 1
            continue
        out.append(delta)
        delta += 1
    return out


def expiration_date_for(patient, clock=None):
    """The withdrawal-report expiration date stamped as of approval."""
    if clock is None:
        clock = db.clock_dt()
    return (clock + timedelta(days=365)).strftime("%Y-%m-%d")