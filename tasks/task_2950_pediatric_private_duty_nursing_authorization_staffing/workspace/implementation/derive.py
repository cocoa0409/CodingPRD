"""Derived quantities: weekly utilization, fill metrics, supervisory cadence,
continuity and match scores, the auto-staff selector and the billing edits.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from store import db
from timeutil import UTC, add_days, add_minutes, week_window, whole_minutes

SKILLS = ["FEEDING_TUBE", "SEIZURE_RESCUE", "TRACH", "VENT"]

UNIT_MINUTES = 15
GRACE_MINUTES = 15
LATE_START_TOLERANCE_MINUTES = 7
EVV_LATE_WINDOW_MINUTES = 60
EVV_EARLY_WINDOW_MINUTES = 15
REST_BUFFER_MINUTES = 60
RENEWAL_MIN_RATIO = Decimal("0.5000")

COMMITTED_STAFFING = ("ASSIGNED", "COMPLETED")
SETTLED_TIMESHEET_STATUS = ("SUBMITTED", "BILL_ACCEPTED")
STAFFABLE_AUTH_STATUS = ("ACTIVE", "REDUCTION_NOTICED", "UNDER_APPEAL", "REDUCED")


# --------------------------------------------------------------------------- #
# numeric helpers
# --------------------------------------------------------------------------- #
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def hours2(value):
    """Hours: two decimal places, round half up, emitted as a JSON number."""
    return float(round_half_up(value, 2))


def ratio4(value):
    """Ratios: four decimal places, round half up, emitted as a JSON number."""
    return float(round_half_up(value, 4))


def units_from_minutes(minutes):
    return int(round_half_up(dec(minutes) / dec(UNIT_MINUTES), 0))


# --------------------------------------------------------------------------- #
# navigation helpers
# --------------------------------------------------------------------------- #
def shifts_of_case(case_id):
    return [s for s in db.shifts.values() if s["case_id"] == case_id]


def case_ids_of_auth(auth_id):
    return {c["id"] for c in db.cases.values() if c["authorization_id"] == auth_id}


def shift_of_assignment(assignment):
    return db.shifts.get(assignment["shift_id"]) if assignment else None


def case_of_shift(shift):
    return db.cases.get(shift["case_id"]) if shift else None


def patient_of_case(case):
    return db.patients.get(case["patient_id"]) if case else None


def auth_of_case(case):
    return db.authorizations.get(case["authorization_id"]) if case else None


def payer_of_auth(auth):
    return db.payers.get(auth["payer_id"]) if auth else None


def plan_of_auth(auth):
    return db.plans.get(auth["plan_of_care_id"]) if auth else None


def case_of_assignment(assignment):
    return case_of_shift(shift_of_assignment(assignment))


def case_of_timesheet(timesheet):
    return case_of_assignment(db.assignments.get(timesheet["shift_assignment_id"]))


def shift_of_timesheet(timesheet):
    return shift_of_assignment(db.assignments.get(timesheet["shift_assignment_id"]))


def active_assignment_of_shift(shift_id):
    rows = [
        a for a in db.assignments.values()
        if a["shift_id"] == shift_id and a["status"] == "ACTIVE"
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[-1] if rows else None


def assignments_of_shift(shift_id):
    return [a for a in db.assignments.values() if a["shift_id"] == shift_id]


def timesheets_of_assignment(assignment_id):
    rows = [t for t in db.timesheets.values() if t["shift_assignment_id"] == assignment_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def timesheets_of_case(case_id):
    out = []
    for t in db.timesheets.values():
        case = case_of_timesheet(t)
        if case is not None and case["id"] == case_id:
            out.append(t)
    return out


def competencies_of_nurse(nurse_id):
    rows = [c for c in db.competencies.values() if c["nurse_id"] == nurse_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# --------------------------------------------------------------------------- #
# authorization weekly utilization (PRD 3.3)
# --------------------------------------------------------------------------- #
def committed_minutes(auth_id, window, exclude_shift_id=None):
    case_ids = case_ids_of_auth(auth_id)
    total = 0
    for shift in db.shifts.values():
        if shift["case_id"] not in case_ids:
            continue
        if exclude_shift_id is not None and shift["id"] == exclude_shift_id:
            continue
        if shift["staffing_status"] not in COMMITTED_STAFFING:
            continue
        if window[0] <= shift["start_at"] < window[1]:
            total += shift["scheduled_minutes"]
    return total


def settled_units(auth_id, window):
    case_ids = case_ids_of_auth(auth_id)
    gross = 0
    net = 0
    for ts in db.timesheets.values():
        if ts["status"] not in SETTLED_TIMESHEET_STATUS:
            continue
        shift = shift_of_timesheet(ts)
        if shift is None or shift["case_id"] not in case_ids:
            continue
        if window[0] <= shift["start_at"] < window[1]:
            gross += int(ts["gross_billable_units"])
            net += int(ts["net_billable_units"])
    return gross, net


def utilization(auth, basis="PROJECTED", week_of=None):
    reference = week_of or db.clock
    window = week_window(reference)
    minutes = committed_minutes(auth["id"], window)
    gross, net = settled_units(auth["id"], window)
    settled_minutes = net * UNIT_MINUTES
    basis_minutes = minutes if basis == "PROJECTED" else settled_minutes
    cap_minutes = dec(auth["approved_hours_per_week"]) * dec(60)
    if cap_minutes == 0:
        util_ratio = Decimal(0)
    else:
        util_ratio = dec(basis_minutes) / cap_minutes
    remaining = max(Decimal(0), cap_minutes - dec(basis_minutes)) / dec(60)
    return {
        "authorization_id": auth["id"],
        "basis": basis,
        "week_start": window[0],
        "week_end": window[1],
        "committed_minutes": minutes,
        "settled_gross_units": gross,
        "settled_net_units": net,
        "settled_minutes": settled_minutes,
        "approved_hours_per_week": hours2(auth["approved_hours_per_week"]),
        "hours_remaining": hours2(remaining),
        "utilization_ratio": ratio4(util_ratio),
    }


def auth_week_hours(auth):
    """(hours_committed_this_week, hours_remaining_this_week) on the projected basis."""
    minutes = committed_minutes(auth["id"], week_window(db.clock))
    committed = round_half_up(dec(minutes) / dec(60), 2)
    cap = dec(auth["approved_hours_per_week"])
    remaining = cap - committed
    if remaining < 0:
        remaining = Decimal(0)
    return float(committed), float(round_half_up(remaining, 2))


def renewal_ratio(auth):
    ws = week_window(db.clock)[0]
    prior = (add_days(ws, -7), ws)
    _gross, net = settled_units(auth["id"], prior)
    settled_minutes = net * UNIT_MINUTES
    cap_minutes = dec(auth["approved_hours_per_week"]) * dec(60)
    if cap_minutes == 0:
        return Decimal(0)
    return round_half_up(dec(settled_minutes) / cap_minutes, 4)


# --------------------------------------------------------------------------- #
# nurse derived values (PRD 2.12, 3.1)
# --------------------------------------------------------------------------- #
def nurse_week_minutes(nurse_id, window, exclude_shift_id=None):
    total = 0
    for assignment in db.assignments.values():
        if assignment["nurse_id"] != nurse_id:
            continue
        if assignment["status"] not in ("ACTIVE", "COMPLETED"):
            continue
        shift = db.shifts.get(assignment["shift_id"])
        if shift is None:
            continue
        if exclude_shift_id is not None and shift["id"] == exclude_shift_id:
            continue
        if window[0] <= shift["start_at"] < window[1]:
            total += shift["scheduled_minutes"]
    return total


def nurse_scheduled_minutes_this_week(nurse_id):
    return nurse_week_minutes(nurse_id, week_window(db.clock))


def verified_skills(nurse_id):
    today = db.clock.date()
    skills = set()
    for comp in db.competencies.values():
        if comp["nurse_id"] != nurse_id:
            continue
        if comp["status"] == "VALID" and comp["expires_on"] > today:
            skills.add(comp["skill"])
    return sorted(skills)


# --------------------------------------------------------------------------- #
# case derived values (PRD 3.4)
# --------------------------------------------------------------------------- #
def visits_of_case(case_id):
    rows = [v for v in db.visits.values() if v["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def base_cadence_days(patient):
    if patient is None:
        return 60
    if patient.get("requires_vent"):
        return 14
    if patient.get("requires_trach"):
        return 30
    return 60


def latest_visit_of_case(case_id):
    rows = visits_of_case(case_id)
    if not rows:
        return None
    rows.sort(key=lambda r: (r["visit_at"], r["created_at"], r["_seq"]))
    return rows[-1]


def cadence_for_case(case, latest_visit=None, patient=None):
    """(cadence_days_applied, anchor_instant) for the supervisory cadence."""
    patient = patient if patient is not None else patient_of_case(case)
    base = base_cadence_days(patient)
    visit = latest_visit if latest_visit is not None else latest_visit_of_case(case["id"])
    if visit is None:
        return base, case["created_at"]
    if visit["outcome"] == "DEFICIENT":
        return int(math.ceil(base / 2.0)), visit["visit_at"]
    return base, visit["visit_at"]


def supervisory_due_at(case):
    cadence, anchor = cadence_for_case(case)
    return add_days(anchor, cadence)


def supervisory_status(case):
    return "OVERDUE" if db.clock >= supervisory_due_at(case) else "CURRENT"


def case_fill_metrics(case):
    auth = auth_of_case(case)
    shifts = shifts_of_case(case["id"])
    denominator = 0
    numerator = 0
    if auth is not None:
        lo, hi = db.clock, auth["effective_end"]
        for shift in shifts:
            if not (lo <= shift["start_at"] < hi):
                continue
            if shift["staffing_status"] == "CANCELLED":
                continue
            denominator += 1
            if shift["staffing_status"] in ("ASSIGNED", "COMPLETED", "PARENT_BACKUP"):
                numerator += 1
    if denominator == 0:
        fill_rate = 1.0
    else:
        fill_rate = ratio4(dec(numerator) / dec(denominator))
    unfilled = 0
    for shift in shifts:
        if shift["staffing_status"] in ("OPEN", "ESCALATED") and shift["start_at"] >= db.clock:
            unfilled += 1
    return fill_rate, unfilled


def case_billed_units(case):
    total = 0
    for ts in timesheets_of_case(case["id"]):
        if ts["status"] == "BILL_ACCEPTED":
            total += int(ts["net_billable_units"])
    return total


# --------------------------------------------------------------------------- #
# continuity and match scores (PRD 3.6)
# --------------------------------------------------------------------------- #
def continuity_score(nurse_id, case, basis="STRICT"):
    matched = 0
    if basis == "STRICT":
        floor_instant = add_days(db.clock, -28)
        for assignment in db.assignments.values():
            if assignment["nurse_id"] != nurse_id or assignment["status"] != "COMPLETED":
                continue
            shift = db.shifts.get(assignment["shift_id"])
            if shift is None or shift["case_id"] != case["id"]:
                continue
            if shift["start_at"] >= floor_instant:
                matched += 1
    else:
        for assignment in db.assignments.values():
            if assignment["nurse_id"] != nurse_id:
                continue
            if assignment["status"] not in ("COMPLETED", "CANCELLED"):
                continue
            shift = db.shifts.get(assignment["shift_id"])
            if shift is None:
                continue
            other_case = db.cases.get(shift["case_id"])
            if other_case is None or other_case["patient_id"] != case["patient_id"]:
                continue
            matched += 1
    return matched, 15 * min(matched, 5)


def matched_skill_count(nurse_id, shift):
    shift_date = shift["start_at"].date()
    count = 0
    for skill in set(shift["required_skills"]):
        for comp in db.competencies.values():
            if comp["nurse_id"] != nurse_id or comp["skill"] != skill:
                continue
            if comp["status"] == "VALID" and comp["expires_on"] > shift_date:
                count += 1
                break
    return count


def match_score(nurse, shift, case):
    if case.get("continuity_nurse_id") == nurse["id"]:
        continuity_pts = 40
    else:
        continuity_pts = min(30, continuity_score(nurse["id"], case, "STRICT")[1])
    matched = matched_skill_count(nurse["id"], shift)
    skill_pts = 10 * min(matched, 3)
    if nurse["license_type"] == "RN" and "VENT" in shift["required_skills"]:
        skill_pts += 10
    minutes = nurse_scheduled_minutes_this_week(nurse["id"])
    availability_pts = max(0, 30 - 5 * (minutes // 240))
    return continuity_pts + skill_pts + availability_pts


# --------------------------------------------------------------------------- #
# overlap rules (PRD 3.5)
# --------------------------------------------------------------------------- #
def nurse_rest_buffer_conflict(nurse_id, shift):
    for assignment in db.assignments.values():
        if assignment["nurse_id"] != nurse_id or assignment["status"] != "ACTIVE":
            continue
        other = db.shifts.get(assignment["shift_id"])
        if other is None or other["id"] == shift["id"]:
            continue
        if shift["start_at"] < add_minutes(other["end_at"], REST_BUFFER_MINUTES) and \
                other["start_at"] < add_minutes(shift["end_at"], REST_BUFFER_MINUTES):
            return True
    return False


def patient_overlap_count(case, shift):
    """Shifts of the patient's cases, ASSIGNED or COMPLETED, strictly overlapping."""
    patient_case_ids = {
        c["id"] for c in db.cases.values() if c["patient_id"] == case["patient_id"]
    }
    count = 0
    for other in db.shifts.values():
        if other["id"] == shift["id"]:
            continue
        if other["case_id"] not in patient_case_ids:
            continue
        if other["staffing_status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        if shift["start_at"] < other["end_at"] and other["start_at"] < shift["end_at"]:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# auto-staff selector (PRD 3.6)
# --------------------------------------------------------------------------- #
def nurse_is_eligible(nurse, shift, case):
    if nurse["status"] != "ACTIVE":
        return False
    if not nurse["license_expires_on"] > shift["end_at"].date():
        return False
    if nurse["id"] in (case.get("excluded_nurse_ids") or []):
        return False
    shift_date = shift["start_at"].date()
    for skill in set(shift["required_skills"]):
        holds = False
        for comp in db.competencies.values():
            if comp["nurse_id"] != nurse["id"] or comp["skill"] != skill:
                continue
            if comp["status"] == "VALID" and comp["expires_on"] > shift_date:
                holds = True
                break
        if not holds:
            return False
    if nurse_rest_buffer_conflict(nurse["id"], shift):
        return False
    window = week_window(shift["start_at"])
    minutes = nurse_week_minutes(nurse["id"], window)
    if minutes + shift["scheduled_minutes"] > int(nurse["max_weekly_hours"]) * 60:
        return False
    return True


def candidate_pool(shift, case):
    window = week_window(shift["start_at"])
    pool = []
    for nurse in db.nurses.values():
        if nurse_is_eligible(nurse, shift, case):
            pool.append(nurse)
    decorated = []
    for nurse in pool:
        decorated.append((
            -match_score(nurse, shift, case),
            nurse_week_minutes(nurse["id"], window),
            nurse["created_at"],
            nurse["_seq"],
            nurse,
        ))
    decorated.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [row[4] for row in decorated]


# --------------------------------------------------------------------------- #
# EVV and billing edits (PRD 3.7)
# --------------------------------------------------------------------------- #
def evv_verified(timesheet, shift):
    return (
        timesheet["evv_method"] in ("GPS", "IVR")
        and bool(timesheet["geo_verified"])
        and timesheet["clock_in_at"] <= add_minutes(shift["start_at"], EVV_LATE_WINDOW_MINUTES)
    )


def recompute_billing(timesheet):
    """The four pinned steps of the billing-edit computation."""
    shift = shift_of_timesheet(timesheet)
    if shift is None or timesheet.get("clock_out_at") is None:
        timesheet["gross_billable_units"] = 0
        timesheet["edit_deduction_units"] = 0
        timesheet["net_billable_units"] = 0
        timesheet["edit_codes"] = _edit_codes(timesheet, shift, False)
        return
    # step 1 -- clamp the worked interval
    raw_minutes = whole_minutes(timesheet["clock_in_at"], timesheet["clock_out_at"])
    capped = min(raw_minutes, shift["scheduled_minutes"] + GRACE_MINUTES)
    if capped < 0:
        capped = 0
    # step 2 -- convert to units exactly once
    gross = units_from_minutes(capped)
    # step 3 -- deduct
    applies = timesheet["evv_method"] == "MANUAL" or shift["evv_status"] == "EXCEPTION"
    if not applies:
        pct = Decimal("0.00")
    elif gross <= 8:
        pct = Decimal("0.05")
    elif gross <= 16:
        pct = Decimal("0.10")
    else:
        pct = Decimal("0.15")
    payer = _payer_for_timesheet(timesheet)
    if applies and payer is not None and payer.get("billing_edit_ruleset") == "STRICT_15MIN":
        pct = pct + Decimal("0.05")
    pct_units = int(math.ceil(dec(gross) * pct)) if gross > 0 else 0
    late = 1 if timesheet["clock_in_at"] > add_minutes(
        shift["start_at"], LATE_START_TOLERANCE_MINUTES) else 0
    deduction = pct_units + late
    # step 4 -- net out
    net = gross - deduction
    if net < 0:
        net = 0
    timesheet["gross_billable_units"] = gross
    timesheet["edit_deduction_units"] = deduction
    timesheet["net_billable_units"] = net
    timesheet["edit_codes"] = _edit_codes(timesheet, shift, late == 1)


def _edit_codes(timesheet, shift, late):
    codes = set()
    if timesheet["evv_method"] == "MANUAL":
        codes.add("MANUAL_ENTRY")
    if shift is not None and shift["evv_status"] == "EXCEPTION":
        codes.add("EVV_EXCEPTION")
    if late:
        codes.add("LATE_START")
    if timesheet.get("_edited"):
        codes.add("POST_EDIT")
    return sorted(codes)


def _payer_for_timesheet(timesheet):
    case = case_of_timesheet(timesheet)
    patient = patient_of_case(case)
    if patient is None:
        return None
    return db.payers.get(patient["payer_id"])
