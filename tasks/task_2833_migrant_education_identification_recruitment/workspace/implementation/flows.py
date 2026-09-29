"""Cross-entity consequences: derived mirrors, ledgers and the two cascades.

Every consequence is recorded rather than inferred, so these helpers are called
inside the same request that triggered them.
"""

from datetime import timedelta
from decimal import Decimal

import calc
from store import base_row, bump, mark_fresh, store, touch_only
from validation import iso_date, parse_iso_date, round_half_up

ZERO = Decimal("0.00")


# --------------------------------------------------------------------------
# derived mirrors on areas and recruiters
# --------------------------------------------------------------------------

def republish_area_counter(area):
    area["assigned_primary_slots_used"] = calc.primary_slots_used(area["id"])


def republish_recruiter_counter(recruiter):
    recruiter["active_assignment_count"] = calc.active_assignment_count(recruiter["id"])


# --------------------------------------------------------------------------
# priority scoring and hour allocation
# --------------------------------------------------------------------------

def persist_pfs(student):
    """Writes pfs_score / pfs_variant / pfs_flag; reports whether the flag moved."""
    assessment = calc.pfs_assessment(student)
    before = student.get("pfs_flag")
    student["pfs_score"] = assessment["pfs_score"]
    student["pfs_variant"] = assessment["pfs_variant"]
    student["pfs_flag"] = assessment["pfs_flag"]
    return before != assessment["pfs_flag"]


def run_allocation(student):
    """Runs the hour-allocation rule and bumps every plan it touches."""
    touched = calc.allocate_hours(student)
    for plan in touched:
        bump(plan)
    return touched


def rederive_service_status(student):
    derived = calc.derive_service_status(student["id"])
    if student.get("service_status") == derived:
        return False
    student["service_status"] = derived
    return True


# --------------------------------------------------------------------------
# the hour / credit ledger
# --------------------------------------------------------------------------

def republish_plan_and_student_ledger(plan, student):
    plan["delivered_hours"] = calc.plan_delivered_hours(plan["id"])
    bump(plan)
    student["total_service_hours_ledger"] = calc.student_ledger_hours(student["id"])
    student["locally_accrued_credits"] = round_half_up(
        calc.locally_accrued_credits(student["id"])
    )
    student["total_awarded_credits"] = round_half_up(
        student["locally_accrued_credits"] + (student.get("transferred_credits_count") or ZERO)
    )
    bump(student)


# --------------------------------------------------------------------------
# plan supersession and closure
# --------------------------------------------------------------------------

def supersede_same_type(student_id, plan_type, new_plan_id):
    for plan in list(store.plans.values()):
        if plan["student_id"] != student_id:
            continue
        if plan["plan_type"] != plan_type:
            continue
        if plan["id"] == new_plan_id:
            continue
        if plan["status"] not in ("DRAFT", "ACTIVE"):
            continue
        plan["status"] = "SUPERSEDED"
        plan["closure_reason"] = "SUPERSEDED"
        plan["superseded_by_plan_id"] = new_plan_id
        bump(plan)


def close_open_plans(student_id, closure_reason):
    closed = []
    for plan in sorted(store.plans.values(), key=lambda p: (p["created_at"], p["id"])):
        if plan["student_id"] != student_id:
            continue
        if plan["status"] not in ("DRAFT", "ACTIVE"):
            continue
        plan["status"] = "CLOSED"
        plan["closure_reason"] = closure_reason
        bump(plan)
        closed.append(plan)
    return closed


# --------------------------------------------------------------------------
# CASCADE-A : certificate approval, four hops
# --------------------------------------------------------------------------

def approval_cascade(coe, student):
    # hop one -- the certificate and the final eligibility window
    start, end, capped = calc.final_window(coe["residency_date"], student["birth_date"])
    coe["status"] = "APPROVED"
    coe["eligibility_start_on"] = iso_date(start)
    coe["eligibility_end_on"] = iso_date(end)
    coe["age_out_capped"] = capped
    bump(coe)

    # hop two -- caused by hop one: a fresh ACTIVE eligibility term
    term = base_row()
    term.update({
        "student_id": student["id"],
        "coe_id": coe["id"],
        "term_start_on": coe["eligibility_start_on"],
        "term_end_on": coe["eligibility_end_on"],
        "status": "ACTIVE",
        "reidentification_due_on": None,
        "superseded_by_term_id": None,
        "termination_reason": None,
    })
    term = _ordered_term(term)
    store.terms[term["id"]] = term
    mark_fresh(term)

    # hop three -- caused by the new ACTIVE term
    student["eligibility_status"] = "ELIGIBLE"
    student["eligibility_expires_on"] = term["term_end_on"]
    _repair_reidentification_chain(student["id"], term)

    # hop four -- caused by hop three's mutation of the child
    persist_pfs(student)
    bump(student)
    run_allocation(student)
    return term


def _repair_reidentification_chain(student_id, new_term):
    orphans = [
        term for term in store.terms.values()
        if term["student_id"] == student_id
        and term["status"] == "REIDENTIFIED"
        and term.get("superseded_by_term_id") is None
    ]
    if not orphans:
        return
    orphans.sort(key=lambda t: (t["term_end_on"], t["created_at"], t["id"]))
    target = orphans[-1]
    greatest = target["term_end_on"]
    tied = [t for t in orphans if t["term_end_on"] == greatest]
    tied.sort(key=lambda t: (t["created_at"], t["id"]))
    target = tied[0]
    target["superseded_by_term_id"] = new_term["id"]
    bump(target)


def _ordered_term(term):
    order = [
        "id", "student_id", "coe_id", "term_start_on", "term_end_on", "status",
        "reidentification_due_on", "superseded_by_term_id", "termination_reason",
        "created_at", "updated_at", "version",
    ]
    return dict((key, term[key]) for key in order if key in term)


# --------------------------------------------------------------------------
# CASCADE-B : certificate invalidation, three hops
# --------------------------------------------------------------------------

def invalidation_cascade(coe, student, reason):
    # hop one
    coe["status"] = "INVALIDATED"
    coe["invalidation_reason"] = reason
    bump(coe)

    # hop two -- caused by hop one
    terminated = []
    for term in sorted(store.terms.values(), key=lambda t: (t["created_at"], t["id"])):
        if term["coe_id"] != coe["id"]:
            continue
        if term["status"] not in ("ACTIVE", "EXPIRING", "EXPIRED"):
            continue
        term["status"] = "TERMINATED"
        term["termination_reason"] = "CERTIFICATE_INVALIDATED"
        bump(term)
        terminated.append(term)

    # hop three -- caused by that termination, not by the invalidate call
    if terminated:
        student["eligibility_status"] = "TERM_EXPIRED"
        student["eligibility_expires_on"] = None
        close_open_plans(student["id"], "ELIGIBILITY_LOST")
        rederive_service_status(student)
        persist_pfs(student)
        bump(student)
    return terminated


# --------------------------------------------------------------------------
# the continuation-of-eligibility sweep
# --------------------------------------------------------------------------

def run_sweep():
    clock_date = store.clock_date()
    batch = calc.sweep_batch()
    result = {
        "swept_count": len(batch),
        "expiring_count": 0,
        "expired_count": 0,
        "lapsed_count": 0,
        "expired_term_ids": [],
    }

    for term in batch:
        student = store.students.get(term["student_id"])
        term_end = parse_iso_date(term["term_end_on"])
        moved = False

        # branch one -- expiry, from ACTIVE or EXPIRING
        if term["status"] in ("ACTIVE", "EXPIRING") and clock_date > term_end:
            term["status"] = "EXPIRED"
            term["reidentification_due_on"] = iso_date(term_end + timedelta(days=45))
            bump(term, force=True)
            if student is not None:
                student["eligibility_status"] = "TERM_EXPIRED"
                student["eligibility_expires_on"] = None
                bump(student, force=True)
            result["expired_count"] += 1
            result["expired_term_ids"].append(term["id"])
            moved = True

        # branch two -- the continuation warning, ACTIVE -> EXPIRING
        elif (term["status"] == "ACTIVE"
              and clock_date >= term_end - timedelta(days=60)
              and clock_date <= term_end):
            term["status"] = "EXPIRING"
            bump(term, force=True)
            if student is not None and student.get("eligibility_status") == "ELIGIBLE":
                student["eligibility_status"] = "CONTINUATION"
                bump(student, force=True)
            result["expiring_count"] += 1
            moved = True

        # branch three -- the lapse, EXPIRED -> LAPSED
        elif term["status"] == "EXPIRED" and term.get("reidentification_due_on"):
            due = parse_iso_date(term["reidentification_due_on"])
            if clock_date > due:
                term["status"] = "LAPSED"
                bump(term, force=True)
                if student is not None:
                    close_open_plans(student["id"], "REIDENTIFICATION_LAPSED")
                    if rederive_service_status(student):
                        bump(student, force=True)
                result["lapsed_count"] += 1
                moved = True

        if not moved:
            continue

    return result
