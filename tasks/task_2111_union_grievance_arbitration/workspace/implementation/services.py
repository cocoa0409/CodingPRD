"""Shared business operations: lookups, cascades and system-origin postings."""

from core import ApiError, db, now, base_record, touch
import derive
from derive import (
    GRIEVANCE_TERMINAL, DEMAND_LIVE_FOR_CASCADE,
    steps_of, offers_of, demands_of, assignments_of,
)


# --------------------------------------------------------------------------
# Lookups — each raises the resource-specific not-found error (PRD 2.9)
# --------------------------------------------------------------------------
def find_unit(unit_id):
    row = db.bargaining_units.get(unit_id)
    if row is None:
        raise ApiError("ERR_BARGAINING_UNIT_NOT_FOUND", "Bargaining unit not found.")
    return row


def find_clause(clause_id):
    row = db.contract_clauses.get(clause_id)
    if row is None:
        raise ApiError("ERR_CLAUSE_NOT_FOUND", "Contract clause not found.")
    return row


def find_employee(employee_id):
    row = db.employees.get(employee_id)
    if row is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND", "Employee not found.")
    return row


def find_grievance(grievance_id):
    row = db.grievances.get(grievance_id)
    if row is None:
        raise ApiError("ERR_GRIEVANCE_NOT_FOUND", "Grievance not found.")
    return row


def find_step(step_id):
    row = db.grievance_steps.get(step_id)
    if row is None:
        raise ApiError("ERR_STEP_NOT_FOUND", "Grievance step not found.")
    return row


def find_offer(offer_id):
    row = db.settlement_offers.get(offer_id)
    if row is None:
        raise ApiError("ERR_OFFER_NOT_FOUND", "Settlement offer not found.")
    return row


def find_precedent(precedent_id):
    row = db.precedent_cases.get(precedent_id)
    if row is None:
        raise ApiError("ERR_PRECEDENT_NOT_FOUND", "Precedent case not found.")
    return row


def find_arbitrator(arbitrator_id):
    row = db.arbitrators.get(arbitrator_id)
    if row is None:
        raise ApiError("ERR_ARBITRATOR_NOT_FOUND", "Arbitrator not found.")
    return row


def find_demand(demand_id):
    row = db.arbitration_demands.get(demand_id)
    if row is None:
        raise ApiError("ERR_DEMAND_NOT_FOUND", "Arbitration demand not found.")
    return row


def find_award(award_id):
    row = db.awards.get(award_id)
    if row is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", "Award not found.")
    return row


def find_cost_entry(entry_id):
    row = db.cost_entries.get(entry_id)
    if row is None:
        raise ApiError("ERR_COST_ENTRY_NOT_FOUND", "Cost entry not found.")
    return row


def find_assignment(assignment_id):
    row = db.witness_assignments.get(assignment_id)
    if row is None:
        raise ApiError("ERR_WITNESS_ASSIGNMENT_NOT_FOUND", "Witness assignment not found.")
    return row


# --------------------------------------------------------------------------
# Ladder position 5 — union-side acts belong to the filing steward alone
# --------------------------------------------------------------------------
def require_filing_steward(grievance, user_id):
    if grievance["filed_by_steward_employee_id"] != user_id:
        raise ApiError(
            "ERR_NOT_FILING_STEWARD",
            "Only the steward who filed this grievance may take union-side action on it.",
        )


# --------------------------------------------------------------------------
# Ladder position 4 — the Grievant's two scoped reads
# --------------------------------------------------------------------------
def require_case_participant(grievance, user_id):
    if grievance["grievant_id"] != user_id:
        raise ApiError("ERR_NOT_CASE_PARTICIPANT", "A grievant may only read their own case.")


# --------------------------------------------------------------------------
# Cost ledger
# --------------------------------------------------------------------------
def create_cost_entry(grievance_id, category, amount_cents, bearing_party, origin):
    entry = base_record()
    entry.update({
        "grievance_id": grievance_id,
        "category": category,
        "amount_cents": amount_cents,
        "bearing_party": bearing_party,
        "incurred_at": now(),
        "origin": origin,
        "status": "POSTED",
        "void_reason": None,
        "voided_by_user_id": None,
    })
    db.cost_entries[entry["id"]] = entry
    return entry


def void_cost_entry(entry, reason, user_id):
    entry["status"] = "VOIDED"
    entry["void_reason"] = reason
    entry["voided_by_user_id"] = user_id
    touch(entry)
    return entry


# --------------------------------------------------------------------------
# Arbitrator engagement
# --------------------------------------------------------------------------
def engage_arbitrator(arbitrator):
    arbitrator["active_case_count"] = arbitrator["active_case_count"] + 1
    touch(arbitrator)


def release_arbitrator(arbitrator):
    arbitrator["active_case_count"] = max(0, arbitrator["active_case_count"] - 1)
    touch(arbitrator)


# --------------------------------------------------------------------------
# Terminal cascade (PRD 3.5)
# --------------------------------------------------------------------------
def cancel_open_steps(grievance):
    for step in steps_of(grievance["id"]):
        if step["status"] in ("SCHEDULED", "HELD"):
            step["status"] = "CANCELLED"
            touch(step)


def void_open_offers(grievance, exclude_offer_id=None):
    for offer in offers_of(grievance["id"]):
        if offer["id"] == exclude_offer_id:
            continue
        if offer["status"] in ("DRAFT", "AUTHORIZED"):
            offer["status"] = "VOIDED"
            touch(offer)


def terminate_live_demands(grievance, new_status):
    for demand in demands_of(grievance["id"]):
        if demand["status"] in DEMAND_LIVE_FOR_CASCADE:
            had_arbitrator = demand["selected_arbitrator_id"]
            demand["status"] = new_status
            touch(demand)
            if had_arbitrator:
                arbitrator = db.arbitrators.get(had_arbitrator)
                if arbitrator is not None:
                    release_arbitrator(arbitrator)


def terminal_cascade(grievance, terminal_status, accepted_offer_id=None):
    """Freeze the posture at its current value, then run the shared cascade."""
    derive.refresh_timeliness(grievance)
    grievance["status"] = terminal_status
    cancel_open_steps(grievance)
    void_open_offers(grievance, exclude_offer_id=accepted_offer_id)
    if terminal_status == "SETTLED":
        terminate_live_demands(grievance, "SETTLED_PRE_HEARING")
    elif terminal_status in ("WITHDRAWN", "CONSOLIDATED"):
        terminate_live_demands(grievance, "WITHDRAWN")


def close_grievance(grievance):
    """Closure after an award becomes fully implemented (PRD 3.8)."""
    derive.refresh_timeliness(grievance)
    grievance["status"] = "CLOSED"
    void_open_offers(grievance)
    touch(grievance)
