"""State transitions with cross-entity consequences: the seat ledger, the
waitlist promotion, the four-hop award cascade and its compensating void.

Every entity a cascade touches is mutated in full -- `updated_at` refreshed and
`version` incremented (PRD 2.4 / 2.8).  Aggregates that PRD 2.8 declares
"recomputed on read" (student totals, GPA, plan ledger, cohort figures) are
never written, so a void restores them with zero drift by construction.
"""
from datetime import timedelta

import derive
from derive import (MODALITY_CODE, center_posture, computed_credits,
                    credits_earned_total, mastery_pct, plan_of_student)
from store import D, fmt_date, new_row, store, touch


# --------------------------------------------------------- logical clock
def clock_date_plus(days):
    return fmt_date(store.clock + timedelta(days=int(days)))


# ------------------------------------------------- seat ledger / posture
def promote_from_waitlist(center):
    """Move at most one WAITLISTED referral of this center to PLACEMENT_OFFERED."""
    candidates = [r for r in store.referrals.values()
                  if r["center_id"] == center["id"] and r["status"] == "WAITLISTED"]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-D(r["priority_score"]), r["created_at"], r["_seq"]))
    winner = candidates[0]
    winner["status"] = "PLACEMENT_OFFERED"
    winner["promoted_from_waitlist"] = True
    winner["offer_expires_on"] = clock_date_plus(5)
    touch(winner)
    return winner


def rederive_center(center, old_posture):
    """Re-derive the posture; promote one waitlisted referral on entry to OPEN."""
    new_posture = center_posture(center)
    if new_posture == "OPEN" and old_posture != "OPEN":
        promote_from_waitlist(center)
    return center_posture(center)


# ---------------------------------------------------- award cascade (3.8)
def transcript_grade_code(final_percent):
    pct = D(final_percent)
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    return "D"


def grade_replacement_mode(enrollment, plan):
    if enrollment["enrollment_type"] == "NEW_CREDIT":
        return "NONE"
    if plan["grade_replacement_policy"] == "REPLACE_ON_RECOVERY":
        return "FULL_REPLACEMENT"
    return "AVERAGED"


def post_award(enrollment, course, placement, plan, credits):
    """Hops 1-4 of the award cascade."""
    # ---- hop 1: the enrollment and the new transcript row
    enrollment["progress_state"] = "AWARDED"
    touch(enrollment)

    mode = grade_replacement_mode(enrollment, plan)
    proctor_ok = derive.has_clean_completed_session(enrollment["id"])
    ncaa = bool(course["ncaa_approved"]) and bool(course["proctoring_required"]) \
        and proctor_ok and credits == D(course["credit_value"])
    modality_code = MODALITY_CODE[course["modality"]]
    award = new_row(
        course_enrollment_id=enrollment["id"],
        student_id=placement["student_id"],
        prior_course_record_id=enrollment["prior_course_record_id"],
        credits_awarded=credits,
        award_basis=placement["credit_policy"],
        grade_replacement_mode=mode,
        transcript_grade_code=transcript_grade_code(enrollment["final_percent"]),
        modality_code=modality_code,
        alt_ed_flag=True,
        transcript_code="%s-%s-AE" % (course["code"], modality_code),
        ncaa_acceptable=ncaa,
        status="POSTED",
        posted_on=store.clock_date(),
        void_reason=None,
    )
    store.awards[award["id"]] = award

    # ---- hop 2: the backing historical row (student totals derive on read)
    if mode == "FULL_REPLACEMENT" and enrollment["prior_course_record_id"]:
        record = store.prior_records.get(enrollment["prior_course_record_id"])
        if record is not None:
            record["replacement_status"] = "REPLACED"
            touch(record)

    # ---- hop 3: the graduation plan ledger and completion
    if plan["status"] == "ACTIVE" and \
            credits_earned_total(plan["student_id"]) >= D(plan["required_credits_total"]):
        plan["status"] = "COMPLETED"
    touch(plan)

    # ---- hop 4: the sending school's cohort figures derive on read
    return award


def void_award(award, void_reason, touch_enrollment=True):
    """Hops 1-4 of the compensating void.

    `touch_enrollment` is False when the caller (resolve-integrity) already owns
    the single version bump the enrollment is entitled to for that request.
    """
    # ---- hop 1
    award["status"] = "VOIDED"
    award["void_reason"] = void_reason
    touch(award)
    enrollment = store.enrollments.get(award["course_enrollment_id"])
    if enrollment is not None and enrollment["progress_state"] == "AWARDED":
        enrollment["progress_state"] = "SUBMITTED_FOR_AWARD"
        if touch_enrollment:
            touch(enrollment)

    # ---- hop 2
    if award["grade_replacement_mode"] == "FULL_REPLACEMENT" and \
            award["prior_course_record_id"]:
        record = store.prior_records.get(award["prior_course_record_id"])
        if record is not None:
            record["replacement_status"] = "NOT_REPLACED"
            touch(record)

    # ---- hop 3
    plan = plan_of_student(award["student_id"])
    if plan is not None:
        if plan["status"] == "COMPLETED" and \
                credits_earned_total(plan["student_id"]) < D(plan["required_credits_total"]):
            plan["status"] = "ACTIVE"
        touch(plan)

    # ---- hop 4: cohort figures derive on read
    return award


# ------------------------------------------------------- exit cascade (3.9)
def exit_placement(placement, exit_reason):
    placement["status"] = "EXITED_UNSUCCESSFUL"
    placement["exit_reason"] = exit_reason
    touch(placement)
    for enrollment in derive.enrollments_of_placement(placement["id"]):
        if enrollment["progress_state"] in ("IN_PROGRESS", "SUBMITTED_FOR_AWARD"):
            enrollment["progress_state"] = "AWARD_DENIED"
            enrollment["denial_reason"] = "PLACEMENT_EXITED"
            touch(enrollment)
        for session in derive.proctor_sessions_of_enrollment(enrollment["id"]):
            if session["status"] == "SCHEDULED":
                session["_released"] = True
    for session in derive.support_sessions_of_placement(placement["id"]):
        if session["status"] == "SCHEDULED":
            session["_released"] = True
