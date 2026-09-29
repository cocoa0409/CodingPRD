"""The recomputation chain, the two student state dimensions and cascades."""

from decimal import Decimal

import calc
import store as st
from store import D, q2

HOLDING_REQUEST_STATUSES = ("DRAFT", "PENDING_ACKNOWLEDGEMENT", "ACKNOWLEDGED",
                            "DISPUTED")


# ------------------------------------------------------------ recompute chain
def compute_picture(student, audit_variant=None, risk_variant=None,
                    cert_term=None, relief=Decimal("0")):
    """Run the chain of PRD 2.11 without writing anything."""
    standing = calc.academic_standing(student)
    resolved_audit = audit_variant or calc.default_audit_variant(student)
    catalog_year = calc.resolve_audit_catalog_year(student, resolved_audit, cert_term)
    transfer_accepted, transfer_contributions = calc.transfer_credit_acceptance(
        student, catalog_year
    )
    audit = calc.credit_audit(student, catalog_year, transfer_accepted)
    contributions = dict(audit["contributions"])
    for enrollment_id, value in transfer_contributions.items():
        contributions[enrollment_id] = value
    bench = calc.progress_benchmark(
        student,
        audit["degree_applicable_credits"],
        standing["completed_full_time_terms"],
        standing["cumulative_gpa"],
        relief,
    )
    resolved_risk = calc.resolve_risk_variant(
        risk_variant, standing["completed_full_time_terms"]
    )
    if resolved_risk == "TERM_SNAPSHOT":
        gpa_basis = calc.term_snapshot_gpa(student)
    else:
        gpa_basis = standing["cumulative_gpa"]
    score, tier = calc.risk_score(
        student, bench["progress_pct"], bench["required_progress_pct"], gpa_basis
    )
    hours = calc.study_hall_hours(
        tier,
        student["missed_class_units_charged"],
        calc.active_assignment_hours(student["id"]),
    )
    return {
        "audit_variant": resolved_audit,
        "risk_variant": resolved_risk,
        "catalog_year": catalog_year,
        "cumulative_gpa": standing["cumulative_gpa"],
        "completed_full_time_terms": standing["completed_full_time_terms"],
        "full_time_term_ids": standing["full_time_term_ids"],
        "transfer_credits_accepted": transfer_accepted,
        "degree_applicable_credits": audit["degree_applicable_credits"],
        "contributions": contributions,
        "progress_pct": bench["progress_pct"],
        "required_progress_pct": bench["required_progress_pct"],
        "benchmark_result": bench["benchmark_result"],
        "failure_reasons": bench["failure_reasons"],
        "risk_score": score,
        "risk_tier": tier,
        "required_study_hall_hours": hours,
    }


def persist_picture(student, picture):
    """Write the chain's output, then re-derive support_status from the new tier."""
    student["cumulative_gpa"] = picture["cumulative_gpa"]
    student["completed_full_time_terms"] = picture["completed_full_time_terms"]
    student["transfer_credits_accepted"] = picture["transfer_credits_accepted"]
    student["degree_applicable_credits"] = picture["degree_applicable_credits"]
    student["progress_pct"] = picture["progress_pct"]
    student["risk_score"] = picture["risk_score"]
    student["risk_tier"] = picture["risk_tier"]
    student["required_study_hall_hours"] = picture["required_study_hall_hours"]
    full_time_terms = picture["full_time_term_ids"]
    for enrollment in calc.student_enrollments(student["id"]):
        if enrollment["id"] in picture["contributions"]:
            enrollment["degree_applicable_credits_counted"] = picture[
                "contributions"
            ][enrollment["id"]]
        if enrollment["status"] == "COMPLETED" and enrollment["credit_source"] == "RESIDENT":
            enrollment["is_full_time_countable"] = enrollment["term_id"] in full_time_terms
        else:
            enrollment["is_full_time_countable"] = False
    derive_support_status(student)


def recompute_student(student):
    """The full chain with persistence (default variants)."""
    picture = compute_picture(student)
    persist_picture(student, picture)
    return picture


def recompute_support_only(student):
    """Refresh the study-hall requirement and re-derive support_status."""
    student["required_study_hall_hours"] = calc.study_hall_hours(
        student["risk_tier"],
        student["missed_class_units_charged"],
        calc.active_assignment_hours(student["id"]),
    )
    derive_support_status(student)


def recompute_risk_and_support(student):
    """Risk score, tier, study-hall requirement and support status."""
    standing = calc.academic_standing(student)
    resolved_audit = calc.default_audit_variant(student)
    catalog_year = calc.resolve_audit_catalog_year(student, resolved_audit)
    transfer_accepted, _ = calc.transfer_credit_acceptance(student, catalog_year)
    audit = calc.credit_audit(student, catalog_year, transfer_accepted)
    bench = calc.progress_benchmark(
        student,
        audit["degree_applicable_credits"],
        standing["completed_full_time_terms"],
        standing["cumulative_gpa"],
    )
    resolved_risk = calc.resolve_risk_variant(
        None, standing["completed_full_time_terms"]
    )
    if resolved_risk == "TERM_SNAPSHOT":
        gpa_basis = calc.term_snapshot_gpa(student)
    else:
        gpa_basis = standing["cumulative_gpa"]
    score, tier = calc.risk_score(
        student, bench["progress_pct"], bench["required_progress_pct"], gpa_basis
    )
    student["risk_score"] = score
    student["risk_tier"] = tier
    recompute_support_only(student)


# ------------------------------------------------------ support_status (3.6)
def top_severity_incidents(student_id):
    return [
        i for i in st.incidents.values()
        if i["student_athlete_id"] == student_id
        and i.get("severity") == "LEVEL_III"
        and i["status"] in ("SUBSTANTIATED", "REMEDIATED")
    ]


def derive_support_status(student):
    current = student["support_status"]
    tier = student["risk_tier"]
    forfeited = int(student["apr_points_forfeited"])
    top = top_severity_incidents(student["id"])
    substantiated_top = [i for i in top if i["status"] == "SUBSTANTIATED"]

    if substantiated_top:
        student["support_status"] = "SUPPORT_WITHHELD"
        return student["support_status"]

    if current == "SUPPORT_WITHHELD":
        if top and tier in ("TIER_2", "TIER_3") and forfeited < 2:
            student["support_status"] = "SUPPORT_MANDATED"
        return student["support_status"]

    if top:
        return current

    if current == "SUPPORT_NORMAL":
        if tier == "TIER_4" or forfeited >= 2:
            student["support_status"] = "SUPPORT_PROBATION"
        elif tier in ("TIER_2", "TIER_3") and forfeited < 2:
            student["support_status"] = "SUPPORT_MANDATED"
    elif current == "SUPPORT_MANDATED":
        if tier == "TIER_4" or forfeited >= 2:
            student["support_status"] = "SUPPORT_PROBATION"
        elif tier == "TIER_1" and forfeited < 2:
            student["support_status"] = "SUPPORT_NORMAL"
    elif current == "SUPPORT_PROBATION":
        if tier in ("TIER_2", "TIER_3") and forfeited < 2:
            student["support_status"] = "SUPPORT_MANDATED"
    return student["support_status"]


# --------------------------------------------------- eligibility_state (3.4)
def governing_certification(student_id):
    best = None
    best_key = None
    for cert in st.certifications.values():
        if cert["student_athlete_id"] != student_id:
            continue
        if cert["status"] == "SUPERSEDED":
            continue
        term = st.terms.get(cert["term_id"])
        index = term["term_index"] if term else 0
        key = (index, cert["created_at"], cert["_seq"])
        if best_key is None or key > best_key:
            best = cert
            best_key = key
    return best


def derive_eligibility_state(student):
    cert = governing_certification(student["id"])
    if cert is None:
        return student["eligibility_state"]
    status = cert["status"]
    if status == "CERTIFIED":
        student["eligibility_state"] = (
            "CERTIFIED" if student.get("declared_program_id") else "PROVISIONALLY_CERTIFIED"
        )
    elif status in ("DENIED", "REVOKED"):
        student["eligibility_state"] = "INELIGIBLE"
    elif status == "RESTORED":
        student["eligibility_state"] = "RESTORED_BY_WAIVER"
    return student["eligibility_state"]


# ----------------------------------------------------- ledgers and cascades
def refresh_missed_class_ledger(student):
    """allowance == charged + remaining after every request (PRD 2.10)."""
    charged = Decimal("0")
    for request in st.requests.values():
        enrollment = st.enrollments.get(request["enrollment_id"])
        if enrollment is None or enrollment["student_athlete_id"] != student["id"]:
            continue
        if request["status"] in HOLDING_REQUEST_STATUSES:
            charged += D(request["missed_units"])
    student["missed_class_units_charged"] = q2(charged)
    student["missed_class_units_remaining"] = q2(
        D(student["missed_class_units_allowance"]) - charged
    )


def refresh_event_charged_total(event):
    total = Decimal("0")
    for request in st.requests.values():
        if request["competition_event_id"] != event["id"]:
            continue
        if request["status"] in HOLDING_REQUEST_STATUSES:
            total += D(request["missed_units"])
    event["charged_units_total"] = q2(total)


def refresh_tutor_capacity(tutor):
    """assigned_weekly_hours == sum of weekly_hours over ACTIVE assignments."""
    total = Decimal("0")
    for a in st.assignments.values():
        if a["tutor_id"] == tutor["id"] and a["status"] == "ACTIVE":
            total += D(a["weekly_hours"])
    if total < 0:
        total = Decimal("0")
    tutor["assigned_weekly_hours"] = q2(total)


def assignment_student(assignment):
    enrollment = st.enrollments.get(assignment["enrollment_id"])
    if enrollment is None:
        return None
    return st.students.get(enrollment["student_athlete_id"])


def cascade_terminate_tutor_assignments(tutor, reason, new_status="TERMINATED",
                                        only_term_id=None):
    """Move PROPOSED/ACTIVE assignments of a tutor out, created_at ASC."""
    rows = [a for a in st.assignments.values() if a["tutor_id"] == tutor["id"]]
    affected = []
    for assignment in st.by_created(rows):
        if assignment["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        if only_term_id is not None:
            enrollment = st.enrollments.get(assignment["enrollment_id"])
            if enrollment is None or enrollment["term_id"] != only_term_id:
                continue
        assignment["status"] = new_status
        assignment["terminated_reason"] = reason
        st.touch(assignment)
        refresh_tutor_capacity(tutor)
        student = assignment_student(assignment)
        if student is not None and student["id"] not in [s["id"] for s in affected]:
            affected.append(student)
    st.touch(tutor)
    for student in affected:
        recompute_support_only(student)
        st.touch(student)
    return affected


def cascade_suspend_tutor(tutor):
    """PRD 3.7/3.9: suspension terminates every PROPOSED or ACTIVE assignment."""
    tutor["status"] = "SUSPENDED"
    return cascade_terminate_tutor_assignments(tutor, "TUTOR_SUSPENDED")
