"""Calculations of PRD 3.2, 3.3, 3.4, 3.6, 3.8 and 3.9 with their constants."""

from datetime import timedelta
from decimal import Decimal

import store as st
from store import D, q1, q2, q4

# --------------------------------------------------------------- constants
GRADE_POINTS = {
    "A": Decimal("4.00"),
    "B": Decimal("3.00"),
    "C": Decimal("2.00"),
    "D": Decimal("1.00"),
    "F": Decimal("0.00"),
}
GRADES = ("A", "B", "C", "D", "F")

REMEDIAL_CREDIT_CAP = Decimal("6")

PTD_GRACE_TERMS = 2
PTD_PCT_PER_TERM = Decimal("0.10")
PROVISIONAL_MIN_GPA = Decimal("1.80")

WEIGHT_GPA = Decimal("0.40")
WEIGHT_PROGRESS = Decimal("0.25")
WEIGHT_MISSED = Decimal("0.20")
WEIGHT_INCIDENT = Decimal("0.15")
GPA_FLOOR_FOR_RISK = Decimal("2.30")
RISK_CUMULATIVE_MIN_TERMS = 2
INCIDENT_POINTS = {"LEVEL_I": 1, "LEVEL_II": 2, "LEVEL_III": 3}
INCIDENT_POINT_SCALE = Decimal("25.00")
PROGRESS_POINT_SCALE = Decimal("400.00")

BASE_STUDY_HALL_HOURS = {
    "TIER_1": Decimal("0.0"),
    "TIER_2": Decimal("4.0"),
    "TIER_3": Decimal("8.0"),
    "TIER_4": Decimal("12.0"),
}
TRAVEL_UNITS_PER_OFFSET_HOUR = Decimal("3")
TRAVEL_OFFSET_CAP = Decimal("4")
TUTOR_CREDIT_BRACKET_HOURS = Decimal("10.0")
TUTOR_CREDIT_CAP_HIGH = Decimal("4.0")
TUTOR_CREDIT_CAP_LOW = Decimal("2.0")
TUTOR_CREDIT_RATE = Decimal("0.5")

TIER_HOURS_CAP = {
    "TIER_1": Decimal("2.0"),
    "TIER_2": Decimal("4.0"),
    "TIER_3": Decimal("8.0"),
    "TIER_4": Decimal("10.0"),
}

MISSED_CLASS_UNIT_MINUTES = Decimal("60")
DEFAULT_MISSED_CLASS_ALLOWANCE = Decimal("9.0")

APR_POINTS_PER_STUDENT = 2
APR_SCALE = Decimal("1000")

TRANSFER_CORE_CAP = Decimal("40.00")
TRANSFER_ELECTIVE_CAP = Decimal("20.00")
TRANSFER_CREDIT_CAP = Decimal("60.00")
TRANSFER_RESIDENCY_TERMS = 1

TUTOR_SUSPENSION_POINT_THRESHOLD = 3
TRAINING_VALIDITY_TERMS = 3
PENALTY_DECAY_TERMS = 2
PENALTY_DECAY_STEP = 1

MAX_APPEAL_ROUNDS = 3
MAX_DISPUTE_ROUNDS = 2
NOTIFICATION_LEAD_DAYS = 7
ACKNOWLEDGEMENT_WINDOW_HOURS = 72
TUTOR_TRAVEL_BUFFER_MINUTES = 20

SPORT_CODES = ("MBB", "WBB", "FB", "BASE", "SOC", "TRACK")
TERM_TYPES = ("FALL", "SPRING", "SUMMER")
APPLICABILITY = ("CORE", "ELECTIVE", "NOT_APPLICABLE")
AUDIT_VARIANTS = ("CATALOG_AT_ENTRY", "CATALOG_AT_CERTIFICATION")
RISK_VARIANTS = ("TERM_SNAPSHOT", "CUMULATIVE")
TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")


# ------------------------------------------------------------------ lookups
def term_of(row):
    return st.terms.get(row.get("term_id"))


def student_enrollments(student_id):
    rows = [e for e in st.enrollments.values() if e["student_athlete_id"] == student_id]
    return st.by_created(rows)


def enrollment_term_index(enrollment):
    term = st.terms.get(enrollment["term_id"])
    return term["term_index"] if term else 0


def enrollment_course(enrollment):
    return st.courses.get(enrollment["course_id"])


def audit_sort_key(enrollment):
    course = enrollment_course(enrollment) or {}
    return (
        enrollment_term_index(enrollment),
        course.get("subject_code", ""),
        course.get("course_number", ""),
        enrollment["created_at"],
        enrollment["_seq"],
    )


def matched_rule(program_id, course_id, catalog_year):
    if not program_id:
        return None
    for rule in st.by_created(list(st.rules.values())):
        if (
            rule["degree_program_id"] == program_id
            and rule["course_id"] == course_id
            and rule["effective_catalog_year"] == catalog_year
        ):
            return rule
    return None


def countable_figure(enrollment, rule):
    earned = D(enrollment.get("earned_credit_hours") or 0)
    if rule is not None and rule.get("max_countable_credits") is not None:
        cap = D(rule["max_countable_credits"])
        if cap < earned:
            return cap
    return earned


# ------------------------------------------- 3.2 academic standing roll-up
def academic_standing(student):
    """cumulative_gpa, completed_full_time_terms and the full-time term set."""
    rows = student_enrollments(student["id"])
    graded = [
        e for e in rows
        if e["status"] == "COMPLETED"
        and e["credit_source"] == "RESIDENT"
        and e.get("grade") in GRADES
    ]
    numerator = Decimal("0")
    denominator = Decimal("0")
    for e in graded:
        attempted = D(e["credit_hours"])
        numerator += D(e["grade_points"]) * attempted
        denominator += attempted
    gpa = q2(numerator / denominator) if denominator > 0 else q2("0")

    per_term = {}
    for e in rows:
        if e["status"] == "COMPLETED" and e["credit_source"] == "RESIDENT":
            per_term.setdefault(e["term_id"], Decimal("0"))
            per_term[e["term_id"]] += D(e["credit_hours"])
    full_time_terms = set()
    for term_id, attempted in per_term.items():
        term = st.terms.get(term_id)
        if term is None:
            continue
        if attempted >= D(term["full_time_credit_minimum"]):
            full_time_terms.add(term_id)
    return {
        "cumulative_gpa": gpa,
        "completed_full_time_terms": len(full_time_terms),
        "full_time_term_ids": full_time_terms,
    }


def full_time_term_indexes(student):
    standing = academic_standing(student)
    out = []
    for term_id in standing["full_time_term_ids"]:
        term = st.terms.get(term_id)
        if term:
            out.append(term["term_index"])
    return sorted(out)


# ------------------------------------- 3.3 transfer-credit acceptance waterfall
def transfer_credit_acceptance(student, catalog_year):
    """Two-bucket waterfall; returns (accepted, per-enrollment contributions)."""
    contributions = {}
    if student.get("transfer_status") != "INCOMING_TRANSFER":
        return q2("0"), contributions
    rows = [
        e for e in student_enrollments(student["id"])
        if e["credit_source"] == "TRANSFER" and e["status"] == "COMPLETED"
    ]
    rows.sort(key=audit_sort_key)
    program_id = student.get("declared_program_id")
    classified = []
    for e in rows:
        rule = matched_rule(program_id, e["course_id"], catalog_year)
        applicability = rule["applicability"] if rule else "NOT_APPLICABLE"
        classified.append((e, rule, applicability))
        contributions[e["id"]] = q2("0")

    bucket_one = Decimal("0")
    for e, rule, applicability in classified:
        if applicability != "CORE":
            continue
        figure = countable_figure(e, rule)
        headroom = TRANSFER_CORE_CAP - bucket_one
        if headroom <= 0:
            continue
        contribution = figure if figure <= headroom else headroom
        bucket_one += contribution
        contributions[e["id"]] = q2(contribution)

    bucket_two = Decimal("0")
    for e, rule, applicability in classified:
        if applicability != "ELECTIVE":
            continue
        figure = countable_figure(e, rule)
        headroom = TRANSFER_ELECTIVE_CAP - bucket_two
        if headroom <= 0:
            continue
        contribution = figure if figure <= headroom else headroom
        bucket_two += contribution
        contributions[e["id"]] = q2(contribution)

    total = bucket_one + bucket_two
    if total > TRANSFER_CREDIT_CAP:
        total = TRANSFER_CREDIT_CAP
    return q2(total), contributions


def resident_completed_term_count(student):
    """Terms holding at least one COMPLETED resident enrollment."""
    term_ids = set()
    for e in student_enrollments(student["id"]):
        if e["status"] == "COMPLETED" and e["credit_source"] == "RESIDENT":
            term_ids.add(e["term_id"])
    return len(term_ids)


# ---------------------------------------------- 3.3 degree-applicability audit
def credit_audit(student, catalog_year, transfer_accepted):
    """Returns the audit result and each enrollment's contribution."""
    contributions = {}
    program_id = student.get("declared_program_id")
    program = st.degree_programs.get(program_id) if program_id else None
    rows = [
        e for e in student_enrollments(student["id"])
        if e["status"] == "COMPLETED"
        and e.get("grade_points") is not None
        and D(e["grade_points"]) > Decimal("0.00")
    ]
    rows.sort(key=audit_sort_key)

    if program is None:
        for e in student_enrollments(student["id"]):
            contributions[e["id"]] = q2("0")
        return {
            "core_total": q2("0"),
            "elective_total": q2("0"),
            "remedial_total": q2("0"),
            "transfer_total": q2(transfer_accepted),
            "degree_applicable_credits": q2(transfer_accepted),
            "contributions": contributions,
        }

    for e in student_enrollments(student["id"]):
        contributions[e["id"]] = q2("0")

    core_total = Decimal("0")
    elective_rows = []
    remedial_rows = []
    entry_index = student["entry_term_index"]

    for e in rows:
        course = enrollment_course(e) or {}
        rule = matched_rule(program_id, e["course_id"], catalog_year)
        applicability = rule["applicability"] if rule else "NOT_APPLICABLE"
        figure = countable_figure(e, rule)
        if course.get("is_remedial"):
            remedial_rows.append((e, figure))
            continue
        if applicability == "CORE":
            core_total += figure
            contributions[e["id"]] = q2(figure)
        elif applicability == "ELECTIVE":
            elective_rows.append((e, figure))

    elective_ceiling = D(program["max_elective_credits_countable"])
    elective_total = Decimal("0")
    for e, figure in elective_rows:
        headroom = elective_ceiling - elective_total
        if headroom <= 0:
            continue
        contribution = figure if figure <= headroom else headroom
        elective_total += contribution
        contributions[e["id"]] = q2(contribution)

    remedial_total = Decimal("0")
    for e, figure in remedial_rows:
        if enrollment_term_index(e) > entry_index + 1:
            continue
        headroom = REMEDIAL_CREDIT_CAP - remedial_total
        if headroom <= 0:
            continue
        contribution = figure if figure <= headroom else headroom
        remedial_total += contribution
        contributions[e["id"]] = q2(contribution)

    total = core_total + elective_total + remedial_total + D(transfer_accepted)
    return {
        "core_total": q2(core_total),
        "elective_total": q2(elective_total),
        "remedial_total": q2(remedial_total),
        "transfer_total": q2(transfer_accepted),
        "degree_applicable_credits": q2(total),
        "contributions": contributions,
    }


def resolve_audit_catalog_year(student, variant, cert_term=None):
    """Which catalog year the active audit variant reads (PRD 3.3)."""
    if variant == "CATALOG_AT_ENTRY":
        return student["entry_catalog_year"]
    if cert_term is not None:
        return cert_term["catalog_year"]
    best = None
    for e in student_enrollments(student["id"]):
        term = st.terms.get(e["term_id"])
        if term is None:
            continue
        if best is None or term["term_index"] > best["term_index"]:
            best = term
    if best is None:
        return student["entry_catalog_year"]
    return best["catalog_year"]


def default_audit_variant(student):
    declared_index = student.get("major_declared_term_index")
    if declared_index is None or declared_index <= student["entry_term_index"]:
        return "CATALOG_AT_ENTRY"
    return "CATALOG_AT_CERTIFICATION"


def resolve_risk_variant(requested, completed_full_time_terms):
    if completed_full_time_terms >= RISK_CUMULATIVE_MIN_TERMS:
        return "CUMULATIVE"
    if requested is None:
        return "TERM_SNAPSHOT"
    return requested


# --------------------------------------- 3.4 progress-benchmark evaluation
def progress_benchmark(student, credits, completed_full_time_terms, gpa,
                       relief=Decimal("0")):
    program_id = student.get("declared_program_id")
    program = st.degree_programs.get(program_id) if program_id else None
    if program is None:
        gpa_ok = D(gpa) >= PROVISIONAL_MIN_GPA
        return {
            "progress_pct": q4("0"),
            "required_progress_pct": q4("0"),
            "benchmark_result": "PASS" if gpa_ok else "FAIL",
            "failure_reasons": [] if gpa_ok else ["GPA_BELOW_MINIMUM"],
            "credit_relief_applied": q2(relief),
        }
    effective = D(credits) + D(relief)
    progress_pct = q4(effective / D(program["total_required_credits"]))
    count = completed_full_time_terms
    if count < PTD_GRACE_TERMS:
        required = q4("0")
    else:
        required = q4(PTD_PCT_PER_TERM * D(count))
        if required > Decimal("1.0000"):
            required = Decimal("1.0000")
    gpa_ok = D(gpa) >= D(program["min_progress_gpa"])
    progress_ok = progress_pct >= required
    reasons = []
    if not progress_ok:
        reasons.append("PROGRESS_BELOW_BENCHMARK")
    if not gpa_ok:
        reasons.append("GPA_BELOW_MINIMUM")
    return {
        "progress_pct": progress_pct,
        "required_progress_pct": required,
        "benchmark_result": "PASS" if (gpa_ok and progress_ok) else "FAIL",
        "failure_reasons": reasons,
        "credit_relief_applied": q2(relief),
    }


# ------------------------------------------------- 3.6 academic risk score
def term_snapshot_gpa(student):
    rows = student_enrollments(student["id"])
    best_index = None
    for e in rows:
        if e["status"] != "COMPLETED":
            continue
        index = enrollment_term_index(e)
        if best_index is None or index > best_index:
            best_index = index
    if best_index is None:
        return q2("0")
    numerator = Decimal("0")
    denominator = Decimal("0")
    for e in rows:
        if (
            e["status"] == "COMPLETED"
            and enrollment_term_index(e) == best_index
            and e.get("grade") in GRADES
        ):
            attempted = D(e["credit_hours"])
            numerator += D(e["grade_points"]) * attempted
            denominator += attempted
    if denominator <= 0:
        return q2("0")
    return q2(numerator / denominator)


def active_assignment_hours(student_id):
    total = Decimal("0")
    for a in st.assignments.values():
        if a["status"] != "ACTIVE":
            continue
        enrollment = st.enrollments.get(a["enrollment_id"])
        if enrollment and enrollment["student_athlete_id"] == student_id:
            total += D(a["weekly_hours"])
    return total


def included_incident_points(student_id):
    total = 0
    for incident in st.incidents.values():
        if incident["student_athlete_id"] != student_id:
            continue
        if incident["status"] in ("SUBSTANTIATED", "REMEDIATED"):
            total += int(incident.get("penalty_points_assessed") or 0)
    return total


def risk_score(student, progress_pct, required_progress_pct, gpa_for_variant):
    shortfall = GPA_FLOOR_FOR_RISK - D(gpa_for_variant)
    if shortfall < 0:
        shortfall = Decimal("0")
    gpa_points = shortfall / GPA_FLOOR_FOR_RISK * Decimal("100.00")
    if gpa_points > Decimal("100.00"):
        gpa_points = Decimal("100.00")
    gpa_points = q2(gpa_points)

    gap = D(required_progress_pct) - D(progress_pct)
    if gap < 0:
        gap = Decimal("0")
    progress_points = gap * PROGRESS_POINT_SCALE
    if progress_points > Decimal("100.00"):
        progress_points = Decimal("100.00")
    progress_points = q2(progress_points)

    allowance = D(student["missed_class_units_allowance"])
    charged = D(student["missed_class_units_charged"])
    if allowance <= 0:
        missed_points = Decimal("100.00") if charged > 0 else Decimal("0.00")
    else:
        missed_points = charged / allowance * Decimal("100.00")
        if missed_points > Decimal("100.00"):
            missed_points = Decimal("100.00")
    missed_points = q2(missed_points)

    incident_points = D(included_incident_points(student["id"])) * INCIDENT_POINT_SCALE
    if incident_points > Decimal("100.00"):
        incident_points = Decimal("100.00")
    incident_points = q2(incident_points)

    score = q2(
        gpa_points * WEIGHT_GPA
        + progress_points * WEIGHT_PROGRESS
        + missed_points * WEIGHT_MISSED
        + incident_points * WEIGHT_INCIDENT
    )
    return score, risk_tier_for(score)


def risk_tier_for(score):
    score = D(score)
    if score < Decimal("20.00"):
        return "TIER_1"
    if score < Decimal("40.00"):
        return "TIER_2"
    if score < Decimal("65.00"):
        return "TIER_3"
    return "TIER_4"


# ---------------------------------------------- 3.6 study-hall obligation
def study_hall_hours(tier, charged_units, active_hours):
    base = BASE_STUDY_HALL_HOURS[tier]
    offset = (D(charged_units) / TRAVEL_UNITS_PER_OFFSET_HOUR).to_integral_value(
        rounding="ROUND_FLOOR"
    )
    if offset > TRAVEL_OFFSET_CAP:
        offset = TRAVEL_OFFSET_CAP
    gross = base + offset
    ceiling = (
        TUTOR_CREDIT_CAP_HIGH if gross >= TUTOR_CREDIT_BRACKET_HOURS
        else TUTOR_CREDIT_CAP_LOW
    )
    credit = TUTOR_CREDIT_RATE * D(active_hours)
    if credit > ceiling:
        credit = ceiling
    result = gross - credit
    if result < 0:
        result = Decimal("0")
    return q1(result)


# ------------------------------------------------- 3.8 missed-class units
def missed_class_units(course, term_start, term_end, departure_at, return_at,
                       multiplier):
    meeting_days = course.get("meeting_days") or []
    start_minute = int(course.get("meeting_start_minute_utc"))
    duration = int(course.get("meeting_duration_minutes"))
    count = 0
    gross = Decimal("0")
    if meeting_days:
        day = (departure_at - timedelta(days=1)).date()
        last = (return_at + timedelta(days=1)).date()
        while day <= last:
            if day.isoweekday() in meeting_days:
                midnight = departure_at.replace(
                    year=day.year, month=day.month, day=day.day,
                    hour=0, minute=0, second=0, microsecond=0,
                )
                meeting_start = midnight + timedelta(minutes=start_minute)
                meeting_end = meeting_start + timedelta(minutes=duration)
                inside = meeting_start >= term_start and meeting_end <= term_end
                if inside:
                    overlap_start = max(meeting_start, departure_at)
                    overlap_end = min(meeting_end, return_at)
                    seconds = (overlap_end - overlap_start).total_seconds()
                    if seconds > 0:
                        count += 1
                        minutes = int(seconds // 60)
                        gross += q2(D(minutes) / MISSED_CLASS_UNIT_MINUTES)
            day = day + timedelta(days=1)
    gross = q2(gross)
    return count, gross, q2(gross * D(multiplier))


# ------------------------------------------- 3.9 tutor penalty decay curve
def newest_closed_reporting_term_index():
    best = None
    for term in st.terms.values():
        if term["apr_status"] == "CLOSED" and term["is_apr_reporting_term"]:
            if best is None or term["term_index"] > best:
                best = term["term_index"]
    return best


def incident_parent_term_index(incident):
    session_id = incident.get("discovered_session_id")
    if not session_id:
        return None
    session = st.sessions.get(session_id)
    if session is None:
        return None
    return session.get("term_index_of_record")


def tutor_penalty_points(tutor_id):
    newest = newest_closed_reporting_term_index()
    rows = [
        i for i in st.incidents.values()
        if i.get("tutor_id") == tutor_id
        and i["status"] in ("SUBSTANTIATED", "REMEDIATED")
    ]
    total = 0
    for incident in st.by_created(rows):
        points = int(incident.get("penalty_points_assessed") or 0)
        parent = incident_parent_term_index(incident)
        if newest is not None and parent is not None:
            if newest - parent > PENALTY_DECAY_TERMS:
                points = points - PENALTY_DECAY_STEP
                if points < 0:
                    points = 0
        total += points
    return total
