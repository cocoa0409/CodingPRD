"""Shared mutation mechanics: existence resolution, bench-spell cascades and the
practice-group settlement that gives a group a new version whenever a request
moved one of its derived numbers (PRD 2.4, 2.10)."""
from decimal import Decimal

from flask import g

from derive import (
    ASSIGNED_ALLOCATION_THRESHOLD_PCT,
    allocated_pct,
    availability,
    derived_snapshot,
    open_spell,
)
from errors import fail
from store import bump, db

NOT_FOUND = {
    "practice_groups": "ERR_PRACTICE_GROUP_NOT_FOUND",
    "skills": "ERR_SKILL_NOT_FOUND",
    "consultants": "ERR_CONSULTANT_NOT_FOUND",
    "skill_assertions": "ERR_SKILL_ASSERTION_NOT_FOUND",
    "demand_opportunities": "ERR_OPPORTUNITY_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "bench_spells": "ERR_BENCH_SPELL_NOT_FOUND",
    "reskilling_programs": "ERR_PROGRAM_NOT_FOUND",
    "subcontractor_firms": "ERR_FIRM_NOT_FOUND",
    "external_placements": "ERR_PLACEMENT_NOT_FOUND",
    "discount_approvals": "ERR_APPROVAL_NOT_FOUND",
    "utilization_periods": "ERR_PERIOD_NOT_FOUND",
    "hiring_forecasts": "ERR_FORECAST_NOT_FOUND",
}


def need(collection, row_id):
    row = db.get(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection], "The referenced %s does not exist." % collection[:-1].replace("_", " "))
    return row


def today():
    return db.clock_date()


def now():
    return db.clock


# ------------------------------------------------------------- bench spells
def open_new_spell(consultant):
    row = db.new_row("bench_spells")
    row.update(
        {
            "consultant_id": consultant["id"],
            "started_on": today(),
            "age_reset_on": None,
            "ended_on": None,
            "state": "MONITORING",
            "escalation_count": 0,
            "reskilling_program_id": None,
            "internal_project_code": None,
            "investment_started_on": None,
            "investment_ended_on": None,
            "separation_proposed_by_user_id": None,
            "separation_decided_by_user_id": None,
            "separation_decision": None,
        }
    )
    return db.insert("bench_spells", row)


def close_spell_after_confirm(consultant):
    """A confirmation that takes committed allocation to at least 50.00 closes
    the consultant's open spell (PRD 3.5)."""
    if allocated_pct(consultant) < ASSIGNED_ALLOCATION_THRESHOLD_PCT:
        return
    spell = open_spell(consultant["id"])
    if spell is None:
        return
    if spell["state"] in ("RESKILLING", "INTERNAL_PROJECT") and spell.get("investment_ended_on") is None:
        spell["investment_ended_on"] = today()
    spell["state"] = "CLOSED"
    spell["ended_on"] = today()
    bump(spell)


def reopen_spell_if_benched(consultant):
    """Hop three of the release cascade: a consultant back on the bench with no
    open spell gets a fresh MONITORING spell (PRD 3.5)."""
    if availability(consultant) != "BENCH":
        return
    if open_spell(consultant["id"]) is not None:
        return
    open_new_spell(consultant)


# --------------------------------------------------------- group settlement
def snapshot_groups():
    g._groups_before = derived_snapshot()


def settle():
    """Give every practice group whose derived tuple moved during this request a
    fresh updated_at and version, before the response body is rendered."""
    before = getattr(g, "_groups_before", None)
    if before is None:
        return
    for group_id, tup in derived_snapshot().items():
        previous = before.get(group_id)
        if previous is not None and previous != tup:
            bump(db.get("practice_groups", group_id))
