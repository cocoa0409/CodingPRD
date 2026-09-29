"""Recompute helpers and the cascade chains of PRD sections 2.6, 3.4, 3.6-3.9."""
from decimal import Decimal

from calc import (HELD_APPOINTMENT_STATUSES, MIN_TERM_MONTHS, benefits_package,
                  encumbered_total, encumbrance, months_in_rank_at_start,
                  salary_floor, term_months_between)
from store import q2, store, touch

HELD_FOR_SEPARATION = ("DRAFT", "OFFER_ISSUED", "OFFER_ACCEPTED", "ACTIVE", "NON_RENEWED")
DOC_VOIDABLE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION")
VISA_VOIDABLE_STATUSES = ("DOCS_PENDING", "SUBMITTED", "RFE_RECEIVED")


# --------------------------------------------------------------------------
# related-record accessors
# --------------------------------------------------------------------------

def appointment_postdoc(appointment):
    return store.postdocs.get(appointment["postdoc_id"])


def appointment_mentor(appointment):
    return store.mentors.get(appointment["mentor_id"])


def appointment_funding(appointment):
    return store.funding_sources.get(appointment["funding_source_id"])


def appointment_visa_cases(appointment_id):
    return [c for c in store.visa_cases.values() if c["appointment_id"] == appointment_id]


def appointment_documents(appointment_id):
    return [d for d in store.development_documents.values()
            if d["appointment_id"] == appointment_id]


def appointment_reviews(appointment_id):
    return [r for r in store.export_control_reviews.values()
            if r["appointment_id"] == appointment_id]


def appointment_grants(appointment_id):
    return [g for g in store.lab_access_grants.values()
            if g["appointment_id"] == appointment_id]


def laboratory_grants(laboratory_id):
    return [g for g in store.lab_access_grants.values()
            if g["laboratory_id"] == laboratory_id]


def appointment_exit_records(appointment_id):
    return [e for e in store.exit_records.values() if e["appointment_id"] == appointment_id]


def appointment_reappointment_reviews(appointment_id):
    return [r for r in store.reappointment_reviews.values()
            if r["appointment_id"] == appointment_id]


def latest_visa_case(appointment_id):
    cases = appointment_visa_cases(appointment_id)
    if not cases:
        return None
    cases.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return cases[-1]


# --------------------------------------------------------------------------
# derived-value recomputation
# --------------------------------------------------------------------------

def refresh_funding_ledger(funding_source):
    encumbered = encumbered_total(funding_source["id"])
    available = q2(q2(funding_source["annual_budget_usd"]) - encumbered)
    if (funding_source["encumbered_usd"] != encumbered
            or funding_source["available_balance_usd"] != available):
        funding_source["encumbered_usd"] = encumbered
        funding_source["available_balance_usd"] = available
        touch(funding_source)


def recompute_rank_figures(appointment):
    """months_in_rank_at_start, term_months and cumulative_months_in_rank_at_end."""
    postdoc = appointment_postdoc(appointment)
    at_start = months_in_rank_at_start(appointment, postdoc)
    months = term_months_between(appointment["term_start_date"], appointment["term_end_date"])
    appointment["months_in_rank_at_start"] = at_start
    appointment["term_months"] = months
    appointment["cumulative_months_in_rank_at_end"] = at_start + months


def recompute_term_and_money(appointment):
    """The recompute set used by every term-changing cascade: term_months,
    cumulative_months_in_rank_at_end, benefits_package, fringe_rate and
    encumbrance_usd, followed by the award ledger."""
    funding_source = appointment_funding(appointment)
    months = term_months_between(appointment["term_start_date"], appointment["term_end_date"])
    appointment["term_months"] = months
    appointment["cumulative_months_in_rank_at_end"] = \
        (appointment["months_in_rank_at_start"] or 0) + months
    appointment["benefits_package"] = benefits_package(appointment, funding_source)
    rate, amount = encumbrance(appointment, funding_source)
    if amount is None:
        appointment["encumbrance_usd"] = Decimal("0.00")
    else:
        appointment["fringe_rate"] = rate
        appointment["encumbrance_usd"] = amount
    touch(appointment)
    refresh_funding_ledger(funding_source)


def preview_term_and_money(appointment, term_end_date):
    """Non-mutating projection used by pre-commit validation."""
    funding_source = appointment_funding(appointment)
    probe = dict(appointment)
    probe["term_end_date"] = term_end_date
    months = term_months_between(probe["term_start_date"], term_end_date)
    _, amount = encumbrance(probe, funding_source)
    if amount is None:
        amount = Decimal("0.00")
    cumulative = (appointment["months_in_rank_at_start"] or 0) + months
    other = Decimal("0.00")
    for other_appointment in store.appointments.values():
        if other_appointment["funding_source_id"] != funding_source["id"]:
            continue
        if other_appointment["id"] == appointment["id"]:
            continue
        if other_appointment["appointment_status"] not in HELD_APPOINTMENT_STATUSES:
            continue
        other += q2(other_appointment.get("encumbrance_usd") or 0)
    encumbered = q2(other + amount)
    available = q2(q2(funding_source["annual_budget_usd"]) - encumbered)
    return {"term_months": months, "cumulative": cumulative,
            "encumbrance": amount, "available_balance": available}


def recompute_salary_floor(appointment):
    funding_source = appointment_funding(appointment)
    appointment["salary_floor_usd"] = salary_floor(
        appointment, funding_source, appointment["months_in_rank_at_start"] or 0)


def release_encumbrance(appointment):
    """Compensating action: the appointment stops charging the award."""
    appointment["encumbrance_usd"] = Decimal("0.00")
    refresh_funding_ledger(appointment_funding(appointment))


# --------------------------------------------------------------------------
# rank ledger postings
# --------------------------------------------------------------------------

def post_rank_months(appointment):
    postdoc = appointment_postdoc(appointment)
    postdoc["total_months_in_rank"] = (postdoc["total_months_in_rank"] or 0) + \
        (appointment["term_months"] or 0)
    touch(postdoc)


def debit_rank_months(appointment):
    postdoc = appointment_postdoc(appointment)
    postdoc["total_months_in_rank"] = (postdoc["total_months_in_rank"] or 0) - \
        (appointment["term_months"] or 0)
    touch(postdoc)


# --------------------------------------------------------------------------
# child voiding / lab grant cascades
# --------------------------------------------------------------------------

def void_appointment_children(appointment, include_visa_case):
    for document in appointment_documents(appointment["id"]):
        if document["status"] in DOC_VOIDABLE_STATUSES:
            document["status"] = "VOIDED"
            touch(document)
    for review in appointment_reviews(appointment["id"]):
        if review["status"] == "QUEUED":
            review["status"] = "VOIDED"
            touch(review)
    if include_visa_case:
        for case in appointment_visa_cases(appointment["id"]):
            if case["status"] in VISA_VOIDABLE_STATUSES:
                case["status"] = "VOIDED"
                touch(case)


def suspend_grants_for_compliance(appointment):
    for grant in appointment_grants(appointment["id"]):
        if grant["status"] == "PROVISIONED":
            grant["status"] = "SUSPENDED"
            grant["suspension_reason"] = "COMPLIANCE_REGRESSION"
            touch(grant)


def restore_suspended_grants(appointment):
    for grant in appointment_grants(appointment["id"]):
        if grant["status"] == "SUSPENDED" and grant["suspension_reason"] == "COMPLIANCE_REGRESSION":
            grant["status"] = "PROVISIONED"
            grant["suspension_reason"] = "NONE"
            touch(grant)


def revoke_grants_for_exit(appointment):
    for grant in appointment_grants(appointment["id"]):
        if grant["status"] in ("PROVISIONED", "SUSPENDED"):
            grant["status"] = "REVOKED"
            grant["suspension_reason"] = "EXIT_PROCESSING"
            touch(grant)


# --------------------------------------------------------------------------
# appointment_status cascades
# --------------------------------------------------------------------------

def withdraw_appointment(appointment, reason):
    """The three withdrawal branches of PRD 3.7 plus the system-driven variants."""
    previous_status = appointment["appointment_status"]
    appointment["appointment_status"] = "WITHDRAWN"
    appointment["withdraw_reason"] = reason
    touch(appointment)
    if previous_status in ("OFFER_ISSUED", "OFFER_ACCEPTED"):
        release_encumbrance(appointment)
        void_appointment_children(appointment, include_visa_case=(previous_status == "OFFER_ACCEPTED"))


def terminate_for_compliance(appointment):
    """CH-E links 3 and 4."""
    appointment["appointment_status"] = "TERMINATED"
    touch(appointment)
    post_rank_months(appointment)
    mentor = appointment_mentor(appointment)
    if mentor is not None:
        mentor["active_postdoc_count"] = max(0, (mentor["active_postdoc_count"] or 0) - 1)
        touch(mentor)
    release_encumbrance(appointment)
    if not appointment_exit_records(appointment["id"]):
        create_exit_record(appointment, "COMPLIANCE_TERMINATION")
    revoke_grants_for_exit(appointment)
    # PRD 3.9: "Once the appointment has left the held population, the server
    # checks whether the scholar has any remaining appointment whose
    # appointment_status is DRAFT, OFFER_ISSUED, OFFER_ACCEPTED, ACTIVE or
    # NON_RENEWED. If none remains, the scholar's own status advances
    # ACTIVE -> SEPARATED". TERMINATED is a terminal state, so this
    # appointment has left the held population (PRD 2.6).
    evaluate_separation(appointment_postdoc(appointment))


def create_exit_record(appointment, exit_reason):
    from store import new_record
    record = new_record()
    record.update({
        "appointment_id": appointment["id"],
        "exit_reason": exit_reason,
        "status": "INITIATED",
        "initiated_at": store.now(),
        "ip_disclosure_count": 0,
        "ip_assignment_signed_at": None,
        "lab_access_cleared": False,
        "final_months_posted": 0,
    })
    store.exit_records[record["id"]] = record
    return record


def lab_access_cleared(appointment_id):
    for grant in appointment_grants(appointment_id):
        if grant["status"] == "PROVISIONED":
            return False
    return True


def evaluate_separation(postdoc):
    if postdoc is None or postdoc["status"] != "ACTIVE":
        return
    for appointment in store.appointments.values():
        if appointment["postdoc_id"] != postdoc["id"]:
            continue
        if appointment["appointment_status"] in HELD_FOR_SEPARATION:
            return
    postdoc["status"] = "SEPARATED"
    touch(postdoc)


def close_exit_record(exit_record):
    """CH-A links 1-4."""
    appointment = store.appointments.get(exit_record["appointment_id"])
    exit_record["status"] = "CLOSED"
    touch(exit_record)
    if appointment is None:
        return
    if appointment["appointment_status"] == "ACTIVE":
        appointment["appointment_status"] = "COMPLETED"
        touch(appointment)
        post_rank_months(appointment)
        exit_record["final_months_posted"] = appointment["term_months"] or 0
        mentor = appointment_mentor(appointment)
        if mentor is not None:
            mentor["active_postdoc_count"] = max(0, (mentor["active_postdoc_count"] or 0) - 1)
            touch(mentor)
        release_encumbrance(appointment)
    evaluate_separation(appointment_postdoc(appointment))


def apply_compliance_outcome(appointment, review):
    """Drive the compliance dimension once no screening cycle remains QUEUED."""
    for other in appointment_reviews(appointment["id"]):
        if other["status"] == "QUEUED":
            return
    outcome = review["status"]
    if outcome == "CLEARED":
        appointment["compliance_status"] = "CLEARED"
        touch(appointment)
        restore_suspended_grants(appointment)
    elif outcome == "CLEARED_WITH_CONDITIONS":
        appointment["compliance_status"] = "RESTRICTED"
        touch(appointment)
    elif outcome == "DENIED":
        appointment["compliance_status"] = "BLOCKED"
        touch(appointment)
        suspend_grants_for_compliance(appointment)
        if appointment["appointment_status"] == "ACTIVE":
            terminate_for_compliance(appointment)


def open_screening_cycle(appointment):
    from store import new_record
    highest = 0
    for review in appointment_reviews(appointment["id"]):
        if review["cycle_index"] > highest:
            highest = review["cycle_index"]
    record = new_record()
    record.update({
        "appointment_id": appointment["id"],
        "cycle_index": highest + 1,
        "status": "QUEUED",
        "restricted_party_hit": False,
        "controlled_technology_flag": False,
        "screening_tier": None,
        "risk_score": None,
        "deemed_export_license_required": False,
        "reviewer_user_id": None,
        "decided_at": None,
    })
    store.export_control_reviews[record["id"]] = record
    return record
