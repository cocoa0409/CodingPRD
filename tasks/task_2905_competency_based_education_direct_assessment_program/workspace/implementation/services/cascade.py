"""State transitions and the two transitive cascades (PRD 2.10, 3.7, 3.8)."""
from decimal import Decimal

import db as store
from db import db, touch
from services import derive, lookup
from services.nums import ONE, ZERO, cents, rhu


# ------------------------------------------------------------- transcripts

def void_transcripts_for_unit_change(student_id):
    for rec in lookup.transcripts_of(student_id):
        if rec["status"] in ("DRAFT", "ISSUED"):
            rec["status"] = "VOIDED"
            rec["voided_reason"] = "UNIT_TOTAL_CHANGED"
            touch(rec)


# ------------------------------------------------------------------- scores

def void_scores(attempt_row, reason):
    for sc in lookup.scores_of(attempt_row["id"]):
        if sc["status"] == "SUBMITTED":
            sc["status"] = "VOIDED"
            sc["voided_reason"] = reason
            touch(sc)


# ------------------------------------------------------------------ awards

def cancel_award(award):
    award["status"] = "CANCELLED"
    award["cancelled_amount_cents"] = award["scheduled_amount_cents"]
    award["outstanding_amount_cents"] = 0
    award["retained_amount_cents"] = 0
    award["returned_amount_cents"] = 0
    award["hold_reason"] = None
    touch(award)


def hold_award(award, reason):
    award["status"] = "HELD"
    award["hold_reason"] = reason
    award["outstanding_amount_cents"] = award["scheduled_amount_cents"]
    award["retained_amount_cents"] = 0
    award["returned_amount_cents"] = 0
    award["cancelled_amount_cents"] = 0
    touch(award)


def aid_equivalency_sweep(term_row):
    """Hop four of the integrity-void cascade."""
    if term_row is None:
        return
    student_row = db.students.get(term_row["student_id"])
    program = lookup.program_of_student(student_row) if student_row else None
    if program is None:
        return
    if derive.credit_equivalency_earned(term_row) >= program["aid_min_credit_equivalency"]:
        return
    for award in lookup.disbursements_of_term(term_row["id"]):
        if award["status"] == "SCHEDULED":
            hold_award(award, "CREDIT_EQUIVALENCY_SHORTFALL")
        elif award["status"] == "DISBURSED" and not award["aid_review_required"]:
            award["aid_review_required"] = True
            touch(award)


# ------------------------------------------------------------- assignments

def end_assignment(asg):
    asg["status"] = "ENDED"
    asg["ended_at_utc"] = db.now()
    for endorsement in asg.get("endorsements", []):
        if not endorsement["consumed"]:
            endorsement["consumed"] = True
    touch(asg)
    mentor_row = db.mentors.get(asg["mentor_id"])
    if mentor_row is not None:
        touch(mentor_row)


# ------------------------------------------------------------------ attempts

def void_attempt(attempt_row):
    """Hops two, three and four of the integrity-void cascade."""
    if attempt_row["status"] == "VOIDED":
        return
    was_mastered = (attempt_row["status"] == "SCORED_MASTERED"
                    and not attempt_row.get("is_provisional_score"))
    attempt_row["_frozen_attempt_number"] = derive.attempt_number(attempt_row)
    attempt_row["status"] = "VOIDED"
    attempt_row["held_from_status"] = None
    touch(attempt_row)
    void_scores(attempt_row, "ATTEMPT_VOIDED")
    if not was_mastered:
        return
    student_row = db.students.get(attempt_row["student_id"])
    term_row = db.terms.get(attempt_row["term_id"]) if attempt_row["term_id"] else None
    if student_row is not None:
        touch(student_row)
        void_transcripts_for_unit_change(student_row["id"])
    if term_row is not None:
        touch(term_row)
    aid_equivalency_sweep(term_row)


# ------------------------------------------------------------------ students

def suspension_sweep(student_row):
    """Sweep in-flight attempts to REVISION_REQUESTED (PRD 3.3)."""
    for att in lookup.attempts_of(student_row["id"]):
        if att["status"] not in ("DRAFT", "UNDER_REVIEW", "ADJUDICATION"):
            continue
        att["status"] = "REVISION_REQUESTED"
        att["final_score_pct"] = None
        att["score_variant"] = None
        att["is_provisional_score"] = False
        att["critical_fail"] = False
        att["revision_count"] = att["revision_count"] + 1
        touch(att)
        void_scores(att, "REVISION_REQUESTED")


def suspend_student(student_row):
    student_row["enrollment_status"] = "SUSPENDED"
    student_row["suspended_at_utc"] = db.now()
    touch(student_row)
    suspension_sweep(student_row)


# ---------------------------------------------------------------------- term

def _earned_figures(term_row, program, outcome, effective_utc):
    attended = store.whole_days_between(term_row["term_start_utc"],
                                        effective_utc)
    nominal = derive.term_days(term_row)
    if outcome == "COMPLETED":
        return attended, rhu(ONE, 4), 0, term_row["tuition_cents"]
    if nominal > 0:
        raw = rhu(Decimal(attended) / Decimal(nominal), 4)
    else:
        raw = rhu(ONE, 4)
    if raw > ONE:
        raw = rhu(ONE, 4)
    if raw >= program["aid_earned_pct_full_threshold"]:
        earned = rhu(ONE, 4)
    else:
        earned = raw
    refund = cents(Decimal(term_row["tuition_cents"]) * (ONE - earned))
    net = term_row["tuition_cents"] - refund
    return attended, earned, refund, net


def close_term(term_row, outcome, effective_utc):
    """Close an ACTIVE term; runs the pinned close-out arithmetic of PRD 3.9."""
    student_row = db.students.get(term_row["student_id"])
    program = lookup.program_of_student(student_row) if student_row else None
    attended, earned, refund, net = _earned_figures(term_row, program, outcome,
                                                    effective_utc)
    term_row["status"] = outcome
    term_row["closed_effective_utc"] = effective_utc
    term_row["attended_days"] = attended
    term_row["earned_pct"] = earned
    term_row["institutional_refund_cents"] = refund
    term_row["net_institutional_charge_cents"] = net
    touch(term_row)
    for att in lookup.attempts_on_term(term_row["id"]):
        if att["status"] in ("DRAFT", "REVISION_REQUESTED"):
            void_attempt(att)
    for award in lookup.disbursements_of_term(term_row["id"]):
        if award["status"] == "SCHEDULED":
            hold_award(award, "TERM_CLOSED")


def cancel_pending_term(term_row, effective_utc):
    """PENDING -> CANCELLED: no attendance to measure, so no arithmetic."""
    term_row["status"] = "CANCELLED"
    term_row["closed_effective_utc"] = effective_utc
    term_row["attended_days"] = 0
    term_row["earned_pct"] = rhu(ZERO, 4)
    term_row["institutional_refund_cents"] = term_row["tuition_cents"]
    term_row["net_institutional_charge_cents"] = 0
    touch(term_row)
    for award in lookup.disbursements_of_term(term_row["id"]):
        if award["status"] in ("SCHEDULED", "HELD"):
            cancel_award(award)


# ------------------------------------------------------- mastery cascade

def after_mastery(attempt_row):
    """Hops two, three and four of the mastery cascade (PRD 3.8)."""
    student_row = db.students.get(attempt_row["student_id"])
    term_row = db.terms.get(attempt_row["term_id"]) if attempt_row["term_id"] else None
    if student_row is None:
        return
    # hop two: the student's and the term's totals move, transcripts void
    touch(student_row)
    if term_row is not None:
        touch(term_row)
    void_transcripts_for_unit_change(student_row["id"])
    # hop three: the changed unit total may graduate the student
    program = lookup.program_of_student(student_row)
    if program is None:
        return
    total = derive.mastered_unit_total(student_row["id"])
    if (student_row["enrollment_status"] == "ACTIVE"
            and total >= program["required_unit_total"]):
        student_row["enrollment_status"] = "GRADUATED"
        student_row["graduated_at_utc"] = db.now()
        student_row["sap_status"] = "GOOD_STANDING"
        touch(student_row)
        # hop four: graduation releases mentoring and closes the open term
        for asg in lookup.assignments_of(student_row["id"]):
            if asg["status"] == "ACTIVE":
                end_assignment(asg)
        for open_term in derive.active_terms(student_row["id"]):
            close_term(open_term, "COMPLETED", db.now())


# ------------------------------------------------------ withdrawal cascade

def withdraw_student(student_row, effective_utc):
    student_row["enrollment_status"] = "WITHDRAWN"
    student_row["withdrawn_at_utc"] = effective_utc
    for open_term in derive.active_terms(student_row["id"]):
        close_term(open_term, "CANCELLED", effective_utc)
    for asg in lookup.assignments_of(student_row["id"]):
        if asg["status"] == "ACTIVE":
            end_assignment(asg)
    for award in lookup.disbursements_of_student(student_row["id"]):
        if award["status"] in ("SCHEDULED", "HELD"):
            cancel_award(award)
    touch(student_row)
