"""Entity serializers: exact field sets per the SCAFFOLD entity tables.

Internal bookkeeping keys (prefixed with '_') are never serialized.
School carries only id + created_at (PRD 2.4 exception).
"""

from decimal import Decimal


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _money_or_number(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def ser_cycle(c):
    out = _common(c)
    out.update(
        {
            "name": c["name"],
            "target_graduation_year": c["target_graduation_year"],
            "total_semifinalist_slots": c["total_semifinalist_slots"],
            "national_award_slots": c["national_award_slots"],
            "national_award_amount_cents": c["national_award_amount_cents"],
            "confirming_floor": c["confirming_floor"],
            "application_deadline": c["application_deadline"],
            "semifinalist_embargo_until": c["semifinalist_embargo_until"],
            "finalist_embargo_until": c["finalist_embargo_until"],
            "award_embargo_until": c["award_embargo_until"],
            "public_embargo_until": c["public_embargo_until"],
            "status": c["status"],
            "matching_run": c["matching_run"],
        }
    )
    return out


def ser_allocation(a):
    out = _common(a)
    out.update(
        {
            "cycle_id": a["cycle_id"],
            "state_code": a["state_code"],
            "graduating_population": a["graduating_population"],
            "quota_raw": _money_or_number(a["quota_raw"]),
            "slots_provisional": a["slots_provisional"],
            "slots_final": a["slots_final"],
            "threshold_selection_index": a["threshold_selection_index"],
            "selected_count": a["selected_count"],
            "status": a["status"],
        }
    )
    return out


def ser_school(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "school_code": s["school_code"],
        "state_code": s["state_code"],
        "created_at": s["created_at"],
    }


def ser_student(s):
    out = _common(s)
    out.update(
        {
            "full_name": s["full_name"],
            "school_id": s["school_id"],
            "state_code": s["state_code"],
            "graduation_year": s["graduation_year"],
            "citizenship_status": s["citizenship_status"],
            "enrollment_status": s["enrollment_status"],
            "parent_sponsor_id": s["parent_sponsor_id"],
        }
    )
    return out


def ser_entry(e):
    out = _common(e)
    out.update(
        {
            "student_id": e["student_id"],
            "cycle_id": e["cycle_id"],
            "exam_year_of_hs": e["exam_year_of_hs"],
            "reading_score": e["reading_score"],
            "writing_score": e["writing_score"],
            "math_score": e["math_score"],
            "selection_index": e["selection_index"],
            "status": e["status"],
            "scored_at": e["scored_at"],
        }
    )
    return out


def ser_application(a):
    out = _common(a)
    out.update(
        {
            "entry_id": a["entry_id"],
            "student_id": a["student_id"],
            "first_choice_college_id": a["first_choice_college_id"],
            "gpa_scaled": a["gpa_scaled"],
            "course_rigor": a["course_rigor"],
            "confirming_selection_index": a["confirming_selection_index"],
            "endorsement_status": a["endorsement_status"],
            "endorsed_by_school_id": a["endorsed_by_school_id"],
            "status": a["status"],
            "return_reason": a["return_reason"],
            "submitted_at": a["submitted_at"],
        }
    )
    return out


def ser_sponsor(s):
    out = _common(s)
    out.update({"legal_name": s["legal_name"], "sponsor_code": s["sponsor_code"]})
    return out


def ser_agreement(a):
    out = _common(a)
    out.update(
        {
            "sponsor_id": a["sponsor_id"],
            "cycle_id": a["cycle_id"],
            "supersedes_agreement_id": a["supersedes_agreement_id"],
            "award_amount_cents": a["award_amount_cents"],
            "max_awards": a["max_awards"],
            "pool_total_cents": a["pool_total_cents"],
            "employee_children_only": a["employee_children_only"],
            "min_selection_index": a["min_selection_index"],
            "effective_start_date": a["effective_start_date"],
            "effective_end_date": a["effective_end_date"],
            "pool_committed_cents": a["pool_committed_cents"],
            "pool_paid_cents": a["pool_paid_cents"],
            "pool_available_reserved_cents": a["pool_available_reserved_cents"],
            "pool_available_cash_cents": a["pool_available_cash_cents"],
            "status": a["status"],
        }
    )
    return out


def ser_college(c):
    out = _common(c)
    out.update(
        {
            "legal_name": c["legal_name"],
            "college_code": c["college_code"],
            "award_amount_cents": c["award_amount_cents"],
            "renewable_years_total": c["renewable_years_total"],
            "terms_per_year": c["terms_per_year"],
            "pool_total_cents": c["pool_total_cents"],
            "max_awards": c["max_awards"],
            "pool_committed_cents": c["pool_committed_cents"],
            "pool_paid_cents": c["pool_paid_cents"],
            "pool_available_reserved_cents": c["pool_available_reserved_cents"],
            "pool_available_cash_cents": c["pool_available_cash_cents"],
            "status": c["status"],
        }
    )
    return out


def ser_award(a):
    out = _common(a)
    out.update(
        {
            "cycle_id": a["cycle_id"],
            "application_id": a["application_id"],
            "student_id": a["student_id"],
            "agreement_id": a["agreement_id"],
            "college_id": a["college_id"],
            "category": a["category"],
            "amount_cents": a["amount_cents"],
            "terms_total": a["terms_total"],
            "renewable_years_total": a["renewable_years_total"],
            "years_renewed": a["years_renewed"],
            "recipient_status": a["recipient_status"],
            "funding_status": a["funding_status"],
            "selection_index_snapshot": a["selection_index_snapshot"],
            "offered_logical_at": a["offered_logical_at"],
            "acceptance_deadline": a["acceptance_deadline"],
        }
    )
    return out


def ser_disbursement(d):
    out = _common(d)
    out.update(
        {
            "award_id": d["award_id"],
            "term_index": d["term_index"],
            "academic_year_index": d["academic_year_index"],
            "scheduled_date": d["scheduled_date"],
            "amount_cents": d["amount_cents"],
            "status": d["status"],
            "released_logical_at": d["released_logical_at"],
        }
    )
    return out


def ser_renewal(r):
    out = _common(r)
    out.update(
        {
            "award_id": r["award_id"],
            "academic_year_index": r["academic_year_index"],
            "reported_enrollment": r["reported_enrollment"],
            "reported_gpa": r["reported_gpa"],
            "status": r["status"],
            "submitted_by_college_id": r["submitted_by_college_id"],
            "decided_logical_at": r["decided_logical_at"],
        }
    )
    return out


def ser_notification(n):
    out = _common(n)
    out.update(
        {
            "student_id": n["student_id"],
            "cycle_id": n["cycle_id"],
            "notice_type": n["notice_type"],
            "sequence_number": n["sequence_number"],
            "embargo_until": n["embargo_until"],
            "status": n["status"],
            "released_logical_at": n["released_logical_at"],
        }
    )
    return out
