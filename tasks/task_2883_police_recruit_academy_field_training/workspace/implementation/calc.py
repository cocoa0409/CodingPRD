"""The eight declared calculations and every derived reading built on them."""
import math
from decimal import Decimal
from fractions import Fraction

from core import ZERO2, d2, d4, ordered, store, today

ATTENDANCE_FACTORS = {
    "PRESENT": Decimal("1.00"),
    "PARTIAL": Decimal("0.75"),
    "ABSENT_EXCUSED": Decimal("0.00"),
    "ABSENT_UNEXCUSED": Decimal("0.00"),
}

SCHEDULED_BASIS_STATUSES = ("PRESENT", "PARTIAL", "ABSENT_EXCUSED")
STAGE_ORDER = ("SCREENING", "ACADEMY", "FIELD_TRAINING", "PROBATION")
LIVE_SESSION_STATUSES = ("SCHEDULED", "UNDER_MIN_ENROLLMENT", "DELIVERED")
COMPETENCY_THRESHOLD = Decimal("4.00")

FITNESS_REFERENCES = {
    "AGE_20_29": {
        "push_ups": Decimal("30"),
        "sit_ups": Decimal("38"),
        "run_1_5_mile_seconds": Decimal("750"),
        "vertical_jump_inches": Decimal("18"),
    },
    "AGE_30_39": {
        "push_ups": Decimal("24"),
        "sit_ups": Decimal("32"),
        "run_1_5_mile_seconds": Decimal("810"),
        "vertical_jump_inches": Decimal("16"),
    },
    "AGE_40_49": {
        "push_ups": Decimal("18"),
        "sit_ups": Decimal("26"),
        "run_1_5_mile_seconds": Decimal("900"),
        "vertical_jump_inches": Decimal("14"),
    },
}

FITNESS_EVENT_KEYS = ("push_ups", "sit_ups", "run_1_5_mile_seconds", "vertical_jump_inches")


# ---------------------------------------------------------------------------
# Exact rounding helpers
# ---------------------------------------------------------------------------

def round_half_up(fraction, places=2):
    """Round an exact Fraction half up to `places` decimals, returning a Decimal."""
    scale = Fraction(10) ** places
    scaled = Fraction(fraction) * scale
    floored = scaled.numerator // scaled.denominator
    if scaled - floored >= Fraction(1, 2):
        floored += 1
    return (Decimal(floored) / (Decimal(10) ** places)).quantize(
        Decimal(1).scaleb(-places)
    )


def frac(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(str(value))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def standard_for_class(cls):
    if cls is None:
        return None
    return store.standards.get(cls.get("certification_standard_id"))


def class_for_recruit(recruit):
    if recruit is None:
        return None
    return store.classes.get(recruit.get("academy_class_id"))


def standard_for_recruit(recruit):
    return standard_for_class(class_for_recruit(recruit))


def topic_codes_of(standard):
    if standard is None:
        return []
    return [t["topic_code"] for t in standard["topic_requirements"]]


def topic_requirement(standard, topic_code):
    if standard is None:
        return None
    for entry in standard["topic_requirements"]:
        if entry["topic_code"] == topic_code:
            return entry
    return None


def class_sessions(class_id):
    return ordered([s for s in store.sessions.values() if s["academy_class_id"] == class_id])


def class_recruits(class_id):
    return ordered([r for r in store.recruits.values() if r["academy_class_id"] == class_id])


def class_entries(class_id):
    return ordered([e for e in store.entries.values() if e["academy_class_id"] == class_id])


def session_attendance(session_id):
    return ordered([a for a in store.attendance.values() if a["course_session_id"] == session_id])


def recruit_attendance(recruit_id):
    return ordered([a for a in store.attendance.values() if a["recruit_id"] == recruit_id])


def recruit_exams(recruit_id):
    return ordered([e for e in store.exams.values() if e["recruit_id"] == recruit_id])


def recruit_screenings(recruit_id):
    return ordered([s for s in store.screenings.values() if s["recruit_id"] == recruit_id])


def recruit_rotations(recruit_id):
    return ordered([r for r in store.rotations.values() if r["recruit_id"] == recruit_id])


def instructor_rotations(instructor_id):
    return ordered(
        [r for r in store.rotations.values() if r["fto_instructor_id"] == instructor_id]
    )


def rotation_reports(rotation_id, include_voided=False):
    rows = [
        r for r in store.reports.values()
        if r["field_training_rotation_id"] == rotation_id
        and (include_voided or not r["voided"])
    ]
    return sorted(rows, key=lambda r: (r["observed_on"], r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# (h) session scheduled hours
# ---------------------------------------------------------------------------

def session_scheduled_hours(starts_at, ends_at):
    seconds = int((ends_at - starts_at).total_seconds())
    return round_half_up(Fraction(seconds, 3600), 2)


# ---------------------------------------------------------------------------
# (a) topic hours ledger  /  (b) the two hour bases
# ---------------------------------------------------------------------------

def row_credited_hours(attendance_row, session):
    factor = ATTENDANCE_FACTORS[attendance_row["status"]]
    present = attendance_row["present_hours"]
    return round_half_up(frac(present) * frac(factor), 2)


def row_counted_absence_hours(attendance_row, session):
    if attendance_row["status"] == "ABSENT_UNEXCUSED":
        return d2(session["scheduled_hours"])
    return ZERO2


def _ledger_rows(recruit_id):
    """CREDITED rows of DELIVERED sessions, in creation order, paired with the session."""
    out = []
    for row in recruit_attendance(recruit_id):
        if row["ledger_status"] != "CREDITED":
            continue
        session = store.sessions.get(row["course_session_id"])
        if session is None or session["status"] != "DELIVERED":
            continue
        out.append((row, session))
    return out


def recruit_per_topic_hours(recruit, basis="ATTENDED"):
    """Map of topic_code -> hours, one entry per topic_requirements entry, declared order."""
    standard = standard_for_recruit(recruit)
    totals = {}
    for code in topic_codes_of(standard):
        totals[code] = ZERO2
    for row, session in _ledger_rows(recruit["id"]):
        code = session["topic_code"]
        if code not in totals:
            totals[code] = ZERO2
        if basis == "SCHEDULED":
            if row["status"] in SCHEDULED_BASIS_STATUSES:
                totals[code] = totals[code] + d2(session["scheduled_hours"])
        else:
            totals[code] = totals[code] + row_credited_hours(row, session)
    return totals


def recruit_total_hours(recruit, basis="ATTENDED"):
    total = ZERO2
    for value in recruit_per_topic_hours(recruit, basis).values():
        total = total + value
    return d2(total)


def recruit_unexcused_absence_hours(recruit):
    total = ZERO2
    for row, session in _ledger_rows(recruit["id"]):
        if row["status"] == "ABSENT_UNEXCUSED":
            total = total + d2(session["scheduled_hours"])
    return d2(total)


def recruit_make_up_hours_owed(recruit):
    total = ZERO2
    for row, session in _ledger_rows(recruit["id"]):
        if row["status"] == "ABSENT_EXCUSED":
            total = total + d2(session["scheduled_hours"])
    return d2(total)


def recruit_remediation_attempts_used(recruit):
    used = 0
    for exam in recruit_exams(recruit["id"]):
        used = max(used, int(exam["attempt_number"]) - 1)
    return used


# ---------------------------------------------------------------------------
# Curriculum verdicts
# ---------------------------------------------------------------------------

def exam_status_map(recruit, standard):
    out = {}
    if standard is None:
        return out
    exams = recruit_exams(recruit["id"])
    for entry in standard["topic_requirements"]:
        if not entry["exam_required"]:
            continue
        code = entry["topic_code"]
        rows = [e for e in exams if e["topic_code"] == code]
        out[code] = rows[-1]["status"] if rows else "NOT_TAKEN"
    return out


def topics_satisfied(recruit, standard):
    if standard is None:
        return False
    per_topic = recruit_per_topic_hours(recruit, "ATTENDED")
    for entry in standard["topic_requirements"]:
        if per_topic.get(entry["topic_code"], ZERO2) < d2(entry["required_hours"]):
            return False
    return True


def exams_all_passed(recruit, standard):
    for status in exam_status_map(recruit, standard).values():
        if status != "PASSED":
            return False
    return True


def curriculum_satisfied(recruit):
    """The academy-completion test: per-topic hours, exams, absence ceiling."""
    standard = standard_for_recruit(recruit)
    if standard is None:
        return False
    if not topics_satisfied(recruit, standard):
        return False
    if not exams_all_passed(recruit, standard):
        return False
    if recruit_unexcused_absence_hours(recruit) > d2(standard["max_absence_hours"]):
        return False
    return True


def eligible_for_certification(recruit):
    """Always on the attended basis: total hours, per-topic hours, exams."""
    standard = standard_for_recruit(recruit)
    if standard is None:
        return False
    if recruit_total_hours(recruit, "ATTENDED") < d2(standard["min_total_hours"]):
        return False
    if not topics_satisfied(recruit, standard):
        return False
    if not exams_all_passed(recruit, standard):
        return False
    return True


# ---------------------------------------------------------------------------
# Cohort readings
# ---------------------------------------------------------------------------

def class_credited_topic_hours_total(cls):
    total = ZERO2
    for entry in class_entries(cls["id"]):
        if entry["kind"] in ("HOURS_CREDIT", "HOURS_REVERSAL"):
            total = total + d2(entry["hours_delta"])
    return d2(total)


def _class_delivered_topic_hours(cls, statuses):
    totals = {}
    for session in class_sessions(cls["id"]):
        if session["status"] not in statuses:
            continue
        code = session["topic_code"]
        totals[code] = totals.get(code, ZERO2) + d2(session["scheduled_hours"])
    return totals


def class_unmet_topic_hours(cls):
    standard = standard_for_class(cls)
    delivered = _class_delivered_topic_hours(cls, ("DELIVERED",))
    out = {}
    if standard is None:
        return out
    for entry in standard["topic_requirements"]:
        code = entry["topic_code"]
        shortfall = d2(entry["required_hours"]) - delivered.get(code, ZERO2)
        out[code] = shortfall if shortfall > ZERO2 else ZERO2
    return out


def class_projected_topic_hours(cls):
    standard = standard_for_class(cls)
    projected = _class_delivered_topic_hours(
        cls, ("DELIVERED", "SCHEDULED", "UNDER_MIN_ENROLLMENT")
    )
    out = {}
    if standard is None:
        return out
    for entry in standard["topic_requirements"]:
        out[entry["topic_code"]] = projected.get(entry["topic_code"], ZERO2)
    return out


def class_has_projection_shortfall(cls):
    standard = standard_for_class(cls)
    if standard is None:
        return False
    projected = class_projected_topic_hours(cls)
    for entry in standard["topic_requirements"]:
        if projected.get(entry["topic_code"], ZERO2) < d2(entry["required_hours"]):
            return True
    return False


def class_graduated_count(cls):
    return len([r for r in class_recruits(cls["id"]) if r["pipeline_stage"] == "CERTIFIED"])


def session_enrolled_count(session):
    return len([a for a in session_attendance(session["id"]) if a["ledger_status"] != "VOIDED"])


def session_credited_hours_total(session):
    total = ZERO2
    for row in session_attendance(session["id"]):
        if row["ledger_status"] == "CREDITED":
            total = total + d2(row["credited_hours"])
    return d2(total)


def instructor_active_trainee_count(instructor):
    return len([
        r for r in instructor_rotations(instructor["id"])
        if r["status"] in ("ACTIVE", "REMEDIAL")
    ])


# ---------------------------------------------------------------------------
# (c) the two competency variants
# ---------------------------------------------------------------------------

def _rating_sum(report):
    return sum(int(v) for v in report["dimension_ratings"].values())


def dor_mean(dimension_ratings):
    total = sum(int(v) for v in dimension_ratings.values())
    return round_half_up(Fraction(total, 5), 2)


def rotation_competency(rotation):
    """Return (competency_score, rolling_mean_score); both null on the empty set."""
    reports = rotation_reports(rotation["id"])
    count = len(reports)
    if count == 0:
        return None, None
    sums = [_rating_sum(r) for r in reports]
    rolling = round_half_up(Fraction(sum(sums), 5 * count), 2)
    k = min(3, count)
    recent = sums[count - k:]
    earlier = sums[: count - k]
    recent_mean = Fraction(sum(recent), 5 * len(recent))
    if earlier:
        earlier_mean = Fraction(sum(earlier), 5 * len(earlier))
    else:
        earlier_mean = recent_mean
    weighted = Fraction(60, 100) * recent_mean + Fraction(40, 100) * earlier_mean
    terminal = round_half_up(weighted, 2)
    return terminal, rolling


def rotation_dor_count(rotation):
    return len(rotation_reports(rotation["id"]))


def rotation_remedial_flag_count(rotation):
    return len([
        r for r in rotation_reports(rotation["id"]) if r["not_responding_to_training"]
    ])


# ---------------------------------------------------------------------------
# (d) physical fitness composite
# ---------------------------------------------------------------------------

def _tier_points(ratio):
    if ratio >= Fraction(120, 100):
        return 25
    if ratio >= Fraction(1):
        return 20
    if ratio >= Fraction(85, 100):
        return 12
    if ratio >= Fraction(70, 100):
        return 6
    return 0


def fitness_composite(raw_metrics, age_bracket, standard):
    """Return (composite_score int, minimum per-event points)."""
    references = FITNESS_REFERENCES[age_bracket]
    points = []
    for key in FITNESS_EVENT_KEYS:
        actual = frac(raw_metrics[key])
        reference = frac(references[key])
        if key == "run_1_5_mile_seconds":
            ratio = reference / actual if actual != 0 else Fraction(0)
        else:
            ratio = actual / reference if reference != 0 else Fraction(0)
        points.append(_tier_points(ratio))
    raw_total = sum(points)
    smallest = min(points)
    floor_points = int(standard["fitness_event_floor_points"])
    if smallest < floor_points:
        return min(raw_total, 59), smallest
    return min(raw_total, 100), smallest


# ---------------------------------------------------------------------------
# Clearance re-derivation
# ---------------------------------------------------------------------------

SCREENING_TYPES = ("BACKGROUND", "MEDICAL", "PSYCHOLOGICAL", "PHYSICAL_FITNESS")


def derive_clearance_status(recruit):
    rows = recruit_screenings(recruit["id"])
    if any(r["status"] == "DISQUALIFIED" for r in rows):
        return "DISQUALIFIED"
    cleared_types = set(
        r["screening_type"] for r in rows if r["status"] in ("CLEARED", "WAIVED")
    )
    if len(cleared_types) == 0:
        return "PENDING"
    if all(t in cleared_types for t in SCREENING_TYPES):
        return "CLEARED"
    return "PARTIAL"


# ---------------------------------------------------------------------------
# (e) probation schedule
# ---------------------------------------------------------------------------

def derive_probation_schedule(recruit):
    """The pinned four-step forward pass. Mutates the recruit row in place."""
    from datetime import timedelta

    start = recruit.get("probation_start")
    if start is None:
        return False
    base_days = int(recruit.get("probation_base_days") or 0)

    # Step 1 - milestone due date, from probation_base_days only.
    milestone_due = start + timedelta(days=int(math.floor(base_days * 0.5)))

    # Step 2 - milestone score by explicit selector.
    eligible = []
    for rot in recruit_rotations(recruit["id"]):
        if rot["status"] not in ("COMPLETED", "REMEDIAL"):
            continue
        if rot["end_date"] > milestone_due:
            continue
        score, _rolling = rotation_competency(rot)
        if score is None:
            continue
        eligible.append((rot, score))
    milestone_score = None
    if eligible:
        eligible.sort(key=lambda pair: (pair[0]["end_date"], pair[0]["created_at"],
                                        pair[0]["_seq"]), reverse=True)
        milestone_score = eligible[0][1]

    # Step 3 - extension tiers from the score alone.
    if milestone_score is None:
        extension = 0
    elif milestone_score >= Decimal("5.00"):
        extension = 0
    elif milestone_score >= Decimal("4.00"):
        extension = 30
    else:
        extension = 60

    # Step 4 - scheduled end, last.
    scheduled_end = start + timedelta(days=base_days + extension)

    recruit["probation_milestone_due_date"] = milestone_due
    recruit["probation_milestone_score"] = milestone_score
    recruit["probation_extension_days"] = extension
    recruit["probation_scheduled_end"] = scheduled_end
    return True


# ---------------------------------------------------------------------------
# (g) attrition and pipeline forecast
# ---------------------------------------------------------------------------

def attrition_analysis(cls):
    entries = class_entries(cls["id"])
    stages = []
    voluntary_total = 0
    survival = Fraction(1)
    for stage in STAGE_ORDER:
        entered_ids = set()
        adverse_ids = set()
        voluntary_ids = set()
        for entry in entries:
            if entry["stage_code"] != stage:
                continue
            if entry["kind"] == "STAGE_ENTRY":
                entered_ids.add(entry["recruit_id"])
            elif entry["kind"] == "ADVERSE_EXIT":
                recruit = store.recruits.get(entry["recruit_id"])
                reason = recruit.get("dismissal_reason_code") if recruit else None
                if reason == "VOLUNTARY_WITHDRAWAL":
                    voluntary_ids.add(entry["recruit_id"])
                else:
                    adverse_ids.add(entry["recruit_id"])
        entered = len(entered_ids)
        adverse = len(adverse_ids)
        voluntary = len(voluntary_ids)
        voluntary_total += voluntary
        if entered == 0:
            rate = None
        else:
            rate = round_half_up(Fraction(adverse, entered), 4)
            survival = survival * (Fraction(1) - frac(rate))
        stages.append({
            "stage_code": stage,
            "entered": entered,
            "adverse_exits": adverse,
            "voluntary_exits": voluntary,
            "attrition_rate": rate,
        })
    survival_rounded = round_half_up(survival, 4)
    rolling_mean_scores = {}
    for rot in ordered(list(store.rotations.values())):
        recruit = store.recruits.get(rot["recruit_id"])
        if recruit is None or recruit["academy_class_id"] != cls["id"]:
            continue
        if rot["status"] not in ("ACTIVE", "REMEDIAL"):
            continue
        _terminal, rolling = rotation_competency(rot)
        rolling_mean_scores[rot["id"]] = rolling
    return {
        "academy_class_id": cls["id"],
        "stages": stages,
        "survival_to_certification": survival_rounded,
        "voluntary_exits_total": voluntary_total,
        "rolling_mean_scores": rolling_mean_scores,
    }


def pipeline_forecast(cls, target):
    analysis = attrition_analysis(cls)
    survival = analysis["survival_to_certification"]
    rates = dict((s["stage_code"], s["attrition_rate"]) for s in analysis["stages"])
    if survival == Decimal("0.0000"):
        required = None
    else:
        required = int(math.ceil(Fraction(int(target)) / frac(survival)))
    per_stage = {}
    if required is None:
        for stage in STAGE_ORDER:
            per_stage[stage] = None
    else:
        current = required
        previous_stage = None
        for stage in STAGE_ORDER:
            if previous_stage is None:
                per_stage[stage] = current
            else:
                rate = rates.get(previous_stage)
                factor = Fraction(1) if rate is None else (Fraction(1) - frac(rate))
                current = int(math.floor(Fraction(current) * factor))
                per_stage[stage] = current
            previous_stage = stage
    return {
        "academy_class_id": cls["id"],
        "target_sworn_officers": int(target),
        "survival_to_certification": survival,
        "required_applicants": required,
        "per_stage_expected": per_stage,
    }
