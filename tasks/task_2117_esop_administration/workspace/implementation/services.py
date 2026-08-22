"""Shared domain helpers: lookups, plan gates, postures and cascades."""

import calc
import responses
from db import DB, serialize, sorted_rows, touch
from errors import fail

# ------------------------------------------------------------------ lookups
_NOT_FOUND = {
    "plans": "ERR_PLAN_NOT_FOUND",
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "valuations": "ERR_VALUATION_NOT_FOUND",
    "loans": "ERR_LOAN_NOT_FOUND",
    "loan_payments": "ERR_LOAN_PAYMENT_NOT_FOUND",
    "allocation_runs": "ERR_RUN_NOT_FOUND",
    "share_allocations": "ERR_ALLOCATION_NOT_FOUND",
    "forfeiture_events": "ERR_FORFEITURE_NOT_FOUND",
    "distribution_elections": "ERR_ELECTION_NOT_FOUND",
    "installment_payments": "ERR_INSTALLMENT_NOT_FOUND",
    "put_option_exercises": "ERR_EXERCISE_NOT_FOUND",
    "participant_statements": "ERR_STATEMENT_NOT_FOUND",
}


def lookup(collection_name, identifier):
    collection = getattr(DB, collection_name)
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        fail(_NOT_FOUND[collection_name])
    return row


def get_plan(identifier):
    return lookup("plans", identifier)


def get_participant(identifier):
    return lookup("participants", identifier)


def get_valuation(identifier):
    return lookup("valuations", identifier)


def get_loan(identifier):
    return lookup("loans", identifier)


def get_run(identifier):
    return lookup("allocation_runs", identifier)


def get_election(identifier):
    return lookup("distribution_elections", identifier)


def get_installment(identifier):
    return lookup("installment_payments", identifier)


def get_exercise(identifier):
    return lookup("put_option_exercises", identifier)


def get_statement(identifier):
    return lookup("participant_statements", identifier)


# ------------------------------------------------------------- plan gates
def check_not_frozen(plan):
    """Validation priority 7 -- fires ahead of the posture check."""
    if plan["plan_status"] == "FROZEN":
        fail("ERR_PLAN_FROZEN")


def require_plan_status(plan, expected):
    """Validation priority 8."""
    if plan["plan_status"] != expected:
        fail("ERR_PLAN_STATE_INVALID")


# --------------------------------------------------------------- postures
def recompute_repurchase_posture(plan):
    plan["repurchase_posture"] = (
        "FUNDED" if plan["repurchase_reserve_cents"] >= plan["repurchase_reserve_floor_cents"]
        else "UNDERFUNDED")
    return plan["repurchase_posture"]


def recompute_forfeiture_posture(plan):
    plan["forfeiture_posture"] = (
        "CLEAR" if plan["unallocated_forfeiture_shares"] <= plan["forfeiture_sweep_threshold_shares"]
        else "SWEEP_REQUIRED")
    return plan["forfeiture_posture"]


# ----------------------------------------------------------- participants
def participants_of_plan(plan_id):
    return [p for p in sorted_rows(DB.participants) if p["plan_id"] == plan_id]


def participant_ids_of_plan(plan_id):
    return {p["id"] for p in DB.participants.values() if p["plan_id"] == plan_id}


def refresh_diversification(participant, plan):
    anchor = calc.diversification_anchor_year(
        participant["date_of_birth"], participant["hire_date"],
        plan["diversification_min_age"], plan["diversification_min_years"])
    participant["diversification_first_eligible_plan_year"] = anchor
    participant["diversification_eligible"] = bool(
        participant["status"] == "ACTIVE"
        and anchor <= plan["plan_year"] <= anchor + calc.QUALIFIED_PERIOD_YEARS - 1)


def recompute_vested_shares(participant):
    participant["vested_shares"] = calc.vested_share_count(
        participant["allocated_shares"], participant["vested_percentage"])


# ----------------------------------------------------- put exercise cascades
def exercises_of_plan(plan_id):
    member_ids = participant_ids_of_plan(plan_id)
    return [x for x in sorted_rows(DB.put_option_exercises)
            if x["participant_id"] in member_ids]


def defer_pending_exercises(plan, skip_id=None):
    for exercise in exercises_of_plan(plan["id"]):
        if exercise["id"] == skip_id:
            continue
        if exercise["status"] == "PENDING":
            exercise["status"] = "DEFERRED"
            touch(exercise)


def restore_deferred_exercises(plan):
    for exercise in exercises_of_plan(plan["id"]):
        if exercise["status"] == "DEFERRED":
            exercise["status"] = "PENDING"
            touch(exercise)


# ------------------------------------------------------------ freeze cascade
def freeze_plan(plan, reason):
    """PRD 3.9 -- the freeze reaches five kinds of child record in one shot."""
    plan["plan_status"] = "FROZEN"
    plan["frozen_reason"] = reason

    for valuation in sorted_rows(DB.valuations):
        if valuation["plan_id"] == plan["id"] and valuation["status"] in ("SUBMITTED", "CHALLENGED"):
            valuation["status"] = "REJECTED"
            valuation["rejected_reason"] = "PLAN_FROZEN"
            touch(valuation)
    plan["open_valuation_count"] = 0

    for run in sorted_rows(DB.allocation_runs):
        if run["plan_id"] == plan["id"] and run["status"] == "DRAFT":
            run["status"] = "VOID"
            run["void_reason"] = "PLAN_FROZEN"
            touch(run)
    plan["draft_run_count"] = 0

    member_ids = participant_ids_of_plan(plan["id"])
    denied_election_ids = set()
    for election in sorted_rows(DB.distribution_elections):
        if election["participant_id"] in member_ids and election["approval_status"] == "REQUESTED":
            election["approval_status"] = "DENIED"
            touch(election)
            denied_election_ids.add(election["id"])

    for installment in sorted_rows(DB.installment_payments):
        if (installment["distribution_election_id"] in denied_election_ids
                and installment["status"] == "SCHEDULED"):
            installment["status"] = "CANCELLED"
            touch(installment)

    for exercise in exercises_of_plan(plan["id"]):
        if exercise["status"] == "PENDING":
            exercise["status"] = "DEFERRED"
            touch(exercise)

    touch(plan)


# ------------------------------------------------------------- list helper
def paged(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return responses.ok_list([serialize(r) for r in window], limit, offset, total)
