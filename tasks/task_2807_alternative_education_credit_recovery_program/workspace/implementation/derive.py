"""Every derived / computed value in the system, recomputed on read.

No derived figure is cached (PRD 2.8).  The only stored progressions are the
explicit accumulators (placement days, enrollment modules and seat hours) and
the state fields the transitions write.
"""
from decimal import Decimal

from store import (D, dmin, floor_int, floor_quarter, fmt_ts, num, ordered, rnd,
                   store)

GRADE_POINTS = {"A": D("4.0"), "B": D("3.0"), "C": D("2.0"), "D": D("1.0"),
                "F": D("0.0")}
GRADE_FACTOR = {9: D("0.25"), 10: D("0.50"), 11: D("0.75"), 12: D("1.00")}
MODALITY_CODE = {"ONLINE": "OL", "PACKET": "PK", "BLENDED": "BL"}

ACTIVE_PLACEMENT_STATES = ("ACTIVE", "RE_ENTRY_PENDING")
RATED_PROGRESS_STATES = ("IN_PROGRESS", "SUBMITTED_FOR_AWARD", "AWARDED")
IN_FLIGHT_PROGRESS_STATES = ("IN_PROGRESS", "SUBMITTED_FOR_AWARD")
NON_TERMINAL_REFERRAL_STATES = ("SUBMITTED", "SCREENING", "INFO_REQUESTED",
                                "PLACEMENT_OFFERED", "WAITLISTED")


# ---------------------------------------------------------------- lookups
def plan_of_student(student_id):
    for plan in ordered(store.plans.values()):
        if plan["student_id"] == student_id:
            return plan
    return None


def placements_of_student(student_id):
    return ordered([p for p in store.placements.values()
                    if p["student_id"] == student_id])


def enrollments_of_placement(placement_id):
    return ordered([e for e in store.enrollments.values()
                    if e["placement_id"] == placement_id])


def awards_of_student(student_id):
    return ordered([a for a in store.awards.values()
                    if a["student_id"] == student_id])


def posted_award_of_enrollment(enrollment_id):
    for a in ordered(store.awards.values()):
        if a["course_enrollment_id"] == enrollment_id and a["status"] == "POSTED":
            return a
    return None


def prior_records_of_student(student_id):
    return ordered([r for r in store.prior_records.values()
                    if r["student_id"] == student_id])


def proctor_sessions_of_enrollment(enrollment_id):
    return ordered([s for s in store.proctor_sessions.values()
                    if s["course_enrollment_id"] == enrollment_id])


def support_sessions_of_placement(placement_id):
    return ordered([s for s in store.support_sessions.values()
                    if s["placement_id"] == placement_id])


def center_of_placement(placement):
    return store.centers.get(placement["center_id"])


# ------------------------------------------------------- Center (PRD 2.7)
def center_metrics(center):
    capacity = center["seat_capacity"]
    fte = D(center["certified_teacher_fte"])
    margin = floor_int(D(capacity) * D("0.10"))
    active = len([p for p in store.placements.values()
                  if p["center_id"] == center["id"]
                  and p["status"] in ACTIVE_PLACEMENT_STATES])
    reserved = len([r for r in store.referrals.values()
                    if r["center_id"] == center["id"]
                    and r["status"] == "PLACEMENT_OFFERED"])
    committed = active + reserved
    available = capacity - committed
    ratio = rnd(D(active) / fte, 2) if fte != 0 else None
    headroom = floor_int(fte * D(center["max_students_per_teacher"])) - active
    if available <= 0 or headroom <= 0:
        posture = "FROZEN"
    elif available <= margin or headroom <= 1:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return {
        "restricted_seat_margin": margin,
        "active_student_count": active,
        "seats_reserved": reserved,
        "seats_committed": committed,
        "seats_available": available,
        "student_teacher_ratio": ratio,
        "staffing_headroom": headroom,
        "intake_posture": posture,
    }


def center_posture(center):
    return center_metrics(center)["intake_posture"]


def staffing_headroom_for(fte, max_per_teacher, active_count):
    return floor_int(D(fte) * D(max_per_teacher)) - active_count


def active_count_of_center(center_id):
    return len([p for p in store.placements.values()
                if p["center_id"] == center_id
                and p["status"] in ACTIVE_PLACEMENT_STATES])


# -------------------------------------------------- HomeSchool (PRD 3.1)
def cohort_figures(school):
    cohort = [s for s in store.students.values()
              if s["home_school_id"] == school["id"]
              and s["cohort_year"] == school["accountability_cohort_year"]]
    size = len(cohort)
    graduates = len([s for s in cohort if student_status(s) == "GRADUATED"])
    placed = len([s for s in cohort if placements_of_student(s["id"])])
    if size == 0:
        rate = None
        flag = "NOT_RATED"
    else:
        rate = rnd(D(graduates) / D(size), 4)
        if rate >= D("0.8500"):
            flag = "COMPLIANT"
        elif rate >= D("0.7000"):
            flag = "WATCH"
        else:
            flag = "PRIORITY"
    return {
        "cohort_size": size,
        "graduates_count": graduates,
        "alt_ed_placed_count": placed,
        "adjusted_grad_rate": rate,
        "cohort_flag": flag,
    }


# ----------------------------------------------------- Student (PRD 3.2)
def student_status(student):
    """Enrollment posture, derived from the plan and the placement chain."""
    plan = plan_of_student(student["id"])
    if plan is not None and plan["status"] == "COMPLETED":
        return "GRADUATED"
    placements = placements_of_student(student["id"])
    if not placements:
        return "ENROLLED_HOME"
    latest = placements[-1]
    if latest["status"] == "RE_ENTERED":
        return "RE_ENTERED"
    if any(p["status"] in ACTIVE_PLACEMENT_STATES for p in placements):
        return "PLACED_ALT"
    if latest["status"] == "EXITED_UNSUCCESSFUL":
        return "EXITED_ALT"
    return "ENROLLED_HOME"


def passed_prior_credits(student_id):
    total = D("0")
    for r in prior_records_of_student(student_id):
        if r["outcome"] == "PASSED":
            total += D(r["credits_attempted"])
    return total


def posted_award_credits(student_id, ncaa_only=False):
    total = D("0")
    for a in awards_of_student(student_id):
        if a["status"] != "POSTED":
            continue
        if ncaa_only and not a["ncaa_acceptable"]:
            continue
        total += D(a["credits_awarded"])
    return total


def credits_earned_total(student_id):
    return rnd(passed_prior_credits(student_id) + posted_award_credits(student_id), 2)


def alt_ed_credits(student_id):
    return rnd(posted_award_credits(student_id), 2)


def ncaa_acceptable_credits(student_id):
    return rnd(posted_award_credits(student_id, ncaa_only=True), 2)


def prior_grade_code(record):
    if record["outcome"] == "INCOMPLETE":
        return "I"
    pct = D(record["original_percent"])
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


def transcript_gpa(student_id):
    rows = []
    for r in prior_records_of_student(student_id):
        if r["replacement_status"] != "NOT_REPLACED":
            continue
        if r["outcome"] not in ("FAILED", "PASSED"):
            continue
        rows.append((GRADE_POINTS[prior_grade_code(r)], D(r["credits_attempted"])))
    for a in awards_of_student(student_id):
        if a["status"] != "POSTED":
            continue
        if D(a["credits_awarded"]) <= 0:
            continue
        rows.append((GRADE_POINTS[a["transcript_grade_code"]], D(a["credits_awarded"])))
    if not rows:
        return None
    quality = D("0")
    credits = D("0")
    for points, cr in rows:
        quality += rnd(points * cr, 3)
        credits += cr
    if credits == 0:
        return None
    return rnd(quality / credits, 2)


# ---------------------------------------------- CourseEnrollment (3.5/3.6)
def _date_from_iso(text):
    from datetime import date as _date
    return _date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def elapsed_days(enrollment):
    return (store.clock_date_obj() - _date_from_iso(enrollment["enrolled_on"])).days


def proctored_exam_percent(enrollment):
    value = None
    for s in proctor_sessions_of_enrollment(enrollment["id"]):
        if s["status"] == "COMPLETED" and s["score_percent"] is not None:
            value = D(s["score_percent"])
    return value


def has_clean_completed_session(enrollment_id):
    for s in proctor_sessions_of_enrollment(enrollment_id):
        if s["status"] == "COMPLETED" and s["integrity_incident"] is False:
            return True
    return False


def has_completed_session(enrollment_id):
    for s in proctor_sessions_of_enrollment(enrollment_id):
        if s["status"] == "COMPLETED":
            return True
    return False


def mastery_pct(enrollment, course=None):
    course = course or store.courses[enrollment["course_id"]]
    if enrollment["module_avg_percent"] is None:
        return None
    module_avg = D(enrollment["module_avg_percent"])
    exam = proctored_exam_percent(enrollment)
    if course["proctoring_required"] and exam is not None:
        weight = D(course["proctored_exam_weight"])
        return rnd((D(1) - weight) * module_avg + weight * exam, 2)
    return rnd(module_avg, 2)


def pace_figures(enrollment, course=None):
    course = course or store.courses[enrollment["course_id"]]
    days = elapsed_days(enrollment)
    if days <= 0:
        return None, "NOT_YET_RATED"
    expected = dmin(D("1.0000"), rnd(D(days) / D(course["pacing_days"]), 4))
    total_modules = D(course["total_modules"])
    passed = dmin(total_modules, D(enrollment["modules_passed"]))
    actual = rnd(passed / total_modules, 4)
    index = rnd(actual / expected, 3)
    if index >= D("0.900"):
        flag = "ON_PACE"
    elif index >= D("0.700"):
        flag = "BEHIND"
    else:
        flag = "CRITICAL"
    return index, flag


def module_fraction(enrollment, course):
    total_modules = D(course["total_modules"])
    passed = dmin(total_modules, D(enrollment["modules_passed"]))
    return rnd(passed / total_modules, 4)


def computed_credits(enrollment, course=None, placement=None):
    """calculations.credit_award_credits -- also CourseEnrollment.projected_credits."""
    course = course or store.courses[enrollment["course_id"]]
    placement = placement or store.placements[enrollment["placement_id"]]
    credit_value = D(course["credit_value"])
    if placement["credit_policy"] == "SEAT_TIME":
        seat_fraction = dmin(
            D("1.0000"),
            rnd(D(enrollment["seat_hours_logged"]) / D(course["required_seat_hours"]), 4),
        )
        return floor_quarter(credit_value * seat_fraction)
    mastery = mastery_pct(enrollment, course)
    if mastery is None:
        return D("0.00")
    if mastery >= D("80.00"):
        return rnd(credit_value, 2)
    if mastery >= D("70.00"):
        return floor_quarter(credit_value * module_fraction(enrollment, course))
    return D("0.00")


def awarded_credits(enrollment):
    award = posted_award_of_enrollment(enrollment["id"])
    if award is None:
        return None
    return rnd(award["credits_awarded"], 2)


# -------------------------------------------------- Placement (PRD 3.9)
def attendance_rate(placement):
    if placement["days_enrolled"] == 0:
        return None
    return rnd(D(placement["days_present"]) / D(placement["days_enrolled"]), 4)


def support_sessions_completed(placement_id):
    return len([s for s in support_sessions_of_placement(placement_id)
                if s["status"] == "COMPLETED"])


def placement_posted_award_credits(placement_id):
    total = D("0")
    for e in enrollments_of_placement(placement_id):
        award = posted_award_of_enrollment(e["id"])
        if award is not None:
            total += D(award["credits_awarded"])
    return total


def readiness_figures(placement):
    rate = attendance_rate(placement)
    attendance_component = rate if rate is not None else D("0.0000")
    rated = [e for e in enrollments_of_placement(placement["id"])
             if e["progress_state"] in RATED_PROGRESS_STATES]
    if not rated:
        pacing_component = D("0.0000")
    else:
        total = D("0")
        for e in rated:
            index, _flag = pace_figures(e)
            total += D("1.0000") if index is None else dmin(D("1.0000"), index)
        pacing_component = rnd(total / D(len(rated)), 4)
    referral = store.referrals.get(placement["referral_id"])
    deficiency = D(referral["deficiency_credits"]) if referral else D("0")
    denominator = deficiency if deficiency > D("0.25") else D("0.25")
    credit_component = rnd(
        dmin(D("1.0000"), placement_posted_award_credits(placement["id"]) / denominator), 4)
    base = rnd(D("0.50") * attendance_component
               + D("0.30") * pacing_component
               + D("0.20") * credit_component, 4)
    sessions = support_sessions_completed(placement["id"])
    if base >= D("0.8000") and sessions >= 2:
        bonus = D("0.0500")
    elif base >= D("0.6500") and sessions >= 1:
        bonus = D("0.0300")
    else:
        bonus = D("0.0000")
    score = rnd(dmin(D("1.0000"), base + bonus), 4)
    return {
        "attendance_rate": rate,
        "support_sessions_completed": sessions,
        "attendance_component": rnd(attendance_component, 4),
        "pacing_component": pacing_component,
        "credit_component": credit_component,
        "readiness_base_score": base,
        "engagement_bonus": bonus,
        "readiness_score": score,
    }


def placement_has_flagged_enrollment(placement_id):
    return any(e["integrity_state"] == "FLAGGED"
               for e in enrollments_of_placement(placement_id))


def re_entry_eligible(placement, figures=None):
    figures = figures or readiness_figures(placement)
    rate = figures["attendance_rate"]
    if rate is None or rate < D("0.9000"):
        return False
    if figures["readiness_score"] < D("0.7500"):
        return False
    if placement_has_flagged_enrollment(placement["id"]):
        return False
    plan = plan_of_student(placement["student_id"])
    if plan is None:
        return False
    if plan["status"] not in ("DRAFT", "ACTIVE", "COMPLETED"):
        return False
    return plan_posture(plan) != "OFF_TRACK"


# ---------------------------------------------- GraduationPlan (PRD 3.2)
def expected_credits_by_grade(plan):
    student = store.students[plan["student_id"]]
    factor = GRADE_FACTOR[student["grade_level"]]
    return rnd(D(plan["required_credits_total"]) * factor, 2)


def plan_credits_in_progress(plan):
    total = D("0")
    for p in placements_of_student(plan["student_id"]):
        for e in enrollments_of_placement(p["id"]):
            if e["progress_state"] in IN_FLIGHT_PROGRESS_STATES:
                total += computed_credits(e)
    return rnd(total, 2)


def plan_credits_remaining(plan):
    earned = credits_earned_total(plan["student_id"])
    remaining = D(plan["required_credits_total"]) - earned
    if remaining < 0:
        remaining = D("0")
    return rnd(remaining, 2)


def plan_posture(plan):
    if plan["status"] == "COMPLETED":
        return "ON_TRACK"
    expected = expected_credits_by_grade(plan)
    earned = credits_earned_total(plan["student_id"])
    if earned >= rnd(expected * D("0.95"), 2):
        return "ON_TRACK"
    if earned >= rnd(expected * D("0.80"), 2):
        return "AT_RISK"
    return "OFF_TRACK"


# ------------------------------------------------------- Referral (3.3)
PATHWAY_WEIGHTS = {
    "CREDIT_DEFICIENCY": (D("0.60"), D("0.20"), D("0.20")),
    "BEHAVIOR": (D("0.20"), D("0.60"), D("0.20")),
    "RE_ENGAGEMENT": (D("0.20"), D("0.20"), D("0.60")),
}


def priority_score(pathway, deficiency_credits, behavior_incident_count,
                   days_disengaged, prior_referral_id):
    deficiency_component = rnd(dmin(D("1.0000"), D(deficiency_credits) / D("8.00")), 4)
    behavior_component = rnd(dmin(D("1.0000"), D(behavior_incident_count) / D(5)), 4)
    disengagement_component = rnd(dmin(D("1.0000"), D(days_disengaged) / D(30)), 4)
    w = PATHWAY_WEIGHTS[pathway]
    base = rnd(rnd(w[0] * deficiency_component, 4)
               + rnd(w[1] * behavior_component, 4)
               + rnd(w[2] * disengagement_component, 4), 4)
    if prior_referral_id is not None:
        return rnd(dmin(D("1.0000"), base + D("0.0500")), 4)
    return base


# -------------------------------------------- ProctorStation / Provider
OCCUPYING_SESSION_STATES = ("SCHEDULED", "COMPLETED")


def station_session_count(station_id):
    return len([s for s in store.proctor_sessions.values()
                if s["proctor_station_id"] == station_id
                and s["status"] in OCCUPYING_SESSION_STATES])


def provider_completed_count(provider_id):
    return len([s for s in store.support_sessions.values()
                if s["support_provider_id"] == provider_id
                and s["status"] == "COMPLETED"])


# ------------------------------------------------------------ serializers
def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_center(row):
    out = _common(row)
    m = center_metrics(row)
    out.update({
        "name": row["name"],
        "seat_capacity": row["seat_capacity"],
        "certified_teacher_fte": num(row["certified_teacher_fte"]),
        "support_staff_fte": num(row["support_staff_fte"]),
        "max_students_per_teacher": row["max_students_per_teacher"],
        "restricted_seat_margin": m["restricted_seat_margin"],
        "seats_reserved": m["seats_reserved"],
        "seats_committed": m["seats_committed"],
        "seats_available": m["seats_available"],
        "active_student_count": m["active_student_count"],
        "student_teacher_ratio": num(m["student_teacher_ratio"]),
        "staffing_headroom": m["staffing_headroom"],
        "intake_posture": m["intake_posture"],
    })
    return out


def ser_home_school(row):
    out = _common(row)
    f = cohort_figures(row)
    out.update({
        "name": row["name"],
        "district_code": row["district_code"],
        "accountability_cohort_year": row["accountability_cohort_year"],
        "cohort_size": f["cohort_size"],
        "graduates_count": f["graduates_count"],
        "alt_ed_placed_count": f["alt_ed_placed_count"],
        "adjusted_grad_rate": num(f["adjusted_grad_rate"]),
        "cohort_flag": f["cohort_flag"],
    })
    return out


def ser_student(row):
    out = _common(row)
    out.update({
        "home_school_id": row["home_school_id"],
        "state_student_id": row["state_student_id"],
        "full_name": row["full_name"],
        "cohort_year": row["cohort_year"],
        "grade_level": row["grade_level"],
        "status": student_status(row),
        "credits_earned_total": num(credits_earned_total(row["id"])),
        "alt_ed_credits": num(alt_ed_credits(row["id"])),
        "ncaa_acceptable_credits": num(ncaa_acceptable_credits(row["id"])),
        "gpa": num(transcript_gpa(row["id"])),
    })
    return out


def ser_course(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "title": row["title"],
        "subject_area": row["subject_area"],
        "credit_value": num(row["credit_value"]),
        "modality": row["modality"],
        "total_modules": row["total_modules"],
        "required_seat_hours": num(row["required_seat_hours"]),
        "pacing_days": row["pacing_days"],
        "proctoring_required": row["proctoring_required"],
        "proctored_exam_weight": num(row["proctored_exam_weight"]),
        "ncaa_approved": row["ncaa_approved"],
        "min_passing_percent": num(row["min_passing_percent"]),
    })
    return out


def ser_prior_record(row):
    out = _common(row)
    out.update({
        "student_id": row["student_id"],
        "course_id": row["course_id"],
        "term_code": row["term_code"],
        "original_percent": num(row["original_percent"]),
        "credits_attempted": num(row["credits_attempted"]),
        "outcome": row["outcome"],
        "original_grade_code": prior_grade_code(row),
        "replacement_status": row["replacement_status"],
    })
    return out


def ser_referral(row):
    out = _common(row)
    out.update({
        "student_id": row["student_id"],
        "center_id": row["center_id"],
        "prior_referral_id": row["prior_referral_id"],
        "pathway": row["pathway"],
        "deficiency_credits": num(row["deficiency_credits"]),
        "behavior_incident_count": row["behavior_incident_count"],
        "days_disengaged": row["days_disengaged"],
        "narrative": row["narrative"],
        "priority_score": num(row["priority_score"]),
        "status": row["status"],
        "screening_note": row["screening_note"],
        "missing_items": row["missing_items"],
        "waitlist_reason": row["waitlist_reason"],
        "denial_reason": row["denial_reason"],
        "offer_expires_on": row["offer_expires_on"],
        "promoted_from_waitlist": row["promoted_from_waitlist"],
    })
    return out


def ser_placement(row):
    out = _common(row)
    f = readiness_figures(row)
    out.update({
        "referral_id": row["referral_id"],
        "student_id": row["student_id"],
        "center_id": row["center_id"],
        "credit_policy": row["credit_policy"],
        "start_date": row["start_date"],
        "status": row["status"],
        "days_present": row["days_present"],
        "days_enrolled": row["days_enrolled"],
        "attendance_rate": num(f["attendance_rate"]),
        "support_sessions_completed": f["support_sessions_completed"],
        "attendance_component": num(f["attendance_component"]),
        "pacing_component": num(f["pacing_component"]),
        "credit_component": num(f["credit_component"]),
        "readiness_base_score": num(f["readiness_base_score"]),
        "engagement_bonus": num(f["engagement_bonus"]),
        "readiness_score": num(f["readiness_score"]),
        "re_entry_eligible": re_entry_eligible(row, f),
        "re_entry_requested_by_user_id": row["re_entry_requested_by_user_id"],
        "target_re_entry_date": row["target_re_entry_date"],
        "actual_re_entry_date": row["actual_re_entry_date"],
        "re_entry_denial_reason": row["re_entry_denial_reason"],
        "exit_reason": row["exit_reason"],
    })
    return out


def ser_enrollment(row):
    out = _common(row)
    course = store.courses[row["course_id"]]
    index, flag = pace_figures(row, course)
    out.update({
        "placement_id": row["placement_id"],
        "course_id": row["course_id"],
        "prior_course_record_id": row["prior_course_record_id"],
        "enrollment_type": row["enrollment_type"],
        "progress_state": row["progress_state"],
        "integrity_state": row["integrity_state"],
        "enrolled_on": row["enrolled_on"],
        "modules_passed": row["modules_passed"],
        "seat_hours_logged": num(row["seat_hours_logged"]),
        "module_avg_percent": num(row["module_avg_percent"]),
        "proctored_exam_percent": num(proctored_exam_percent(row)),
        "mastery_pct": num(mastery_pct(row, course)),
        "final_percent": num(row["final_percent"]),
        "pace_index": num(index),
        "pacing_flag": flag,
        "projected_credits": num(computed_credits(row, course)),
        "awarded_credits": num(awarded_credits(row)),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "integrity_incident_code": row["integrity_incident_code"],
        "integrity_resolution_note": row["integrity_resolution_note"],
        "denial_reason": row["denial_reason"],
    })
    return out


def ser_award(row):
    out = _common(row)
    out.update({
        "course_enrollment_id": row["course_enrollment_id"],
        "student_id": row["student_id"],
        "prior_course_record_id": row["prior_course_record_id"],
        "credits_awarded": num(row["credits_awarded"]),
        "award_basis": row["award_basis"],
        "grade_replacement_mode": row["grade_replacement_mode"],
        "transcript_grade_code": row["transcript_grade_code"],
        "modality_code": row["modality_code"],
        "alt_ed_flag": row["alt_ed_flag"],
        "transcript_code": row["transcript_code"],
        "ncaa_acceptable": row["ncaa_acceptable"],
        "status": row["status"],
        "posted_on": row["posted_on"],
        "void_reason": row["void_reason"],
    })
    return out


def ser_plan(row):
    out = _common(row)
    out.update({
        "student_id": row["student_id"],
        "required_credits_total": num(row["required_credits_total"]),
        "grade_replacement_policy": row["grade_replacement_policy"],
        "projected_completion_term": row["projected_completion_term"],
        "status": row["status"],
        "credits_earned": num(credits_earned_total(row["student_id"])),
        "credits_in_progress": num(plan_credits_in_progress(row)),
        "credits_remaining": num(plan_credits_remaining(row)),
        "expected_credits_by_grade": num(expected_credits_by_grade(row)),
        "posture": plan_posture(row),
    })
    return out


def ser_station(row):
    out = _common(row)
    out.update({
        "center_id": row["center_id"],
        "label": row["label"],
        "station_type": row["station_type"],
        "turnaround_buffer_minutes": row["turnaround_buffer_minutes"],
        "scheduled_session_count": station_session_count(row["id"]),
    })
    return out


def ser_proctor_session(row):
    out = _common(row)
    out.update({
        "course_enrollment_id": row["course_enrollment_id"],
        "proctor_station_id": row["proctor_station_id"],
        "scheduled_start": fmt_ts(row["scheduled_start"]),
        "scheduled_end": fmt_ts(row["scheduled_end"]),
        "status": row["status"],
        "score_percent": num(row["score_percent"]),
        "integrity_incident": row["integrity_incident"],
        "no_show_note": row["no_show_note"],
    })
    return out


def ser_provider(row):
    out = _common(row)
    out.update({
        "center_id": row["center_id"],
        "role_type": row["role_type"],
        "full_name": row["full_name"],
        "max_concurrent_students": row["max_concurrent_students"],
        "completed_session_count": provider_completed_count(row["id"]),
    })
    return out


def ser_support_session(row):
    out = _common(row)
    out.update({
        "support_provider_id": row["support_provider_id"],
        "placement_id": row["placement_id"],
        "start_at": fmt_ts(row["start_at"]),
        "end_at": fmt_ts(row["end_at"]),
        "service_code": row["service_code"],
        "status": row["status"],
        "minutes_delivered": row["minutes_delivered"],
        "completion_note": row["completion_note"],
    })
    return out
