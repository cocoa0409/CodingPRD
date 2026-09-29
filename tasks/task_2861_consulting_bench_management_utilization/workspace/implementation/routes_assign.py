"""Internal staffing: proposing, confirming, releasing and cancelling
assignments (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import serial
from derive import (
    MARGIN_FLOOR_PCT,
    assertion_status,
    assertions_for,
    availability,
    effective_rate,
    group_posture,
    match_score,
    peak_allocation,
    reference_assertion,
    travel_fit,
)
from envelope import collection, obj
from errors import bad_request, fail
from helpers import q2
from ops import close_spell_after_confirm, need, reopen_spell_if_benched, settle, today
from reqctx import (
    begin,
    body,
    filter_enum,
    filter_value,
    opt_str,
    pagination,
    req_date,
    req_dec,
    req_enum,
    req_id,
    req_int,
    window,
)
from routes_demand import new_assignment
from store import bump, db

bp = Blueprint("assignments", __name__)

READ_ROLES = ("ResourceManager", "PracticePartner", "FinanceController", "SalesLead", "Consultant")
STATUSES = ("PROPOSED", "CONFIRMED", "ACTIVE", "RELEASED", "CANCELLED")
CATEGORIES = ("BILLABLE", "INVESTMENT")


@bp.post("/assignments")
def propose_assignment():
    begin("ResourceManager")
    payload = body(
        allowed=(
            "consultant_id",
            "demand_opportunity_id",
            "allocation_pct",
            "start_date",
            "end_date",
            "category",
            "expected_consultant_version",
        ),
        required=(
            "consultant_id",
            "demand_opportunity_id",
            "allocation_pct",
            "start_date",
            "end_date",
            "category",
            "expected_consultant_version",
        ),
    )
    consultant_id = req_id(payload, "consultant_id")
    demand_id = req_id(payload, "demand_opportunity_id")
    allocation = req_dec(payload, "allocation_pct", Decimal("1.00"), Decimal("100.00"))
    start = req_date(payload, "start_date")
    end = req_date(payload, "end_date")
    if end <= start:
        bad_request("Field 'end_date' must be strictly later than 'start_date'.")
    category = req_enum(payload, "category", CATEGORIES)
    expected = req_int(payload, "expected_consultant_version", 1)
    consultant = need("consultants", consultant_id)
    demand = need("demand_opportunities", demand_id)
    if consultant["version"] != expected:
        fail("ERR_STALE_CONSULTANT_VERSION", "The consultant has moved on since that version was read.")
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFIED demand may take an assignment.")
    if demand.get("staffing_mode") is None:
        fail("ERR_STAFFING_MODE_NOT_SET", "The demand has not chosen a staffing branch yet.")
    if availability(consultant) == "SEPARATED":
        fail("ERR_CONSULTANT_SEPARATED", "That consultant has been separated.")
    if demand["staffing_mode"] != "INTERNAL":
        fail("ERR_STAFFING_MODE_MISMATCH", "Only an INTERNAL demand takes a named consultant.")
    row = new_assignment(
        consultant, demand, allocation, start, end, category, match_score(consultant, demand)
    )
    bump(consultant)
    return obj(serial.assignment(row), 201)


@bp.get("/assignments")
def list_assignments():
    begin(*READ_ROLES)
    limit, offset = pagination()
    consultant_id = filter_value("consultant_id")
    demand_id = filter_value("demand_opportunity_id")
    status = filter_enum("status", STATUSES)
    category = filter_enum("category", CATEGORIES)
    rows = db.all("assignments")
    if consultant_id is not None:
        rows = [r for r in rows if r["consultant_id"] == consultant_id]
    if demand_id is not None:
        rows = [r for r in rows if r["demand_opportunity_id"] == demand_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    begin(*READ_ROLES)
    return obj(serial.assignment(need("assignments", assignment_id)))


@bp.post("/assignments/<assignment_id>/confirm")
def confirm_assignment(assignment_id):
    begin("ResourceManager")
    assignment = need("assignments", assignment_id)
    body(allowed=())
    if assignment["status"] != "PROPOSED":
        fail("ERR_ASSIGNMENT_STATE_INVALID", "Only a PROPOSED assignment may be confirmed.")
    demand = db.get("demand_opportunities", assignment["demand_opportunity_id"])
    consultant = db.get("consultants", assignment["consultant_id"])
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The demand is no longer QUALIFIED.")
    if demand.get("staffing_mode") != "INTERNAL":
        fail("ERR_STAFFING_MODE_MISMATCH", "Only an INTERNAL demand takes a confirmed assignment.")
    status = availability(consultant)
    if status == "SEPARATED":
        fail("ERR_CONSULTANT_SEPARATED", "That consultant has been separated.")
    if status == "RESKILLING":
        fail("ERR_CONSULTANT_IN_RESKILLING", "That consultant is mid-cohort and cannot be staffed.")
    held = assertions_for(consultant["id"], demand["required_skill_id"])
    if not held:
        fail("ERR_PROFICIENCY_INSUFFICIENT", "The consultant asserts no proficiency in the required skill.")
    if not any(assertion_status(row) == "ACTIVE" for row in held):
        fail("ERR_CERTIFICATION_EXPIRED", "The backing certification has lapsed.")
    reference = reference_assertion(consultant["id"], demand["required_skill_id"])
    if reference["proficiency_level"] < demand["min_proficiency_level"]:
        fail("ERR_PROFICIENCY_INSUFFICIENT", "The asserted proficiency is below the demand's minimum.")
    if travel_fit(consultant, demand) <= 0:
        fail("ERR_TRAVEL_CONSTRAINT_VIOLATED", "The demand's travel profile exceeds the consultant's tolerance.")
    if assignment["category"] == "INVESTMENT" and group_posture(demand["practice_group_id"]) == "FROZEN":
        fail("ERR_PRACTICE_POSTURE_FROZEN", "A frozen practice may not take on investment work.")
    peak = peak_allocation(
        consultant["id"], assignment["start_date"], assignment["end_date"], exclude_id=assignment["id"]
    )
    if peak + assignment["allocation_pct"] > Decimal("100.00"):
        fail("ERR_ALLOCATION_CAPACITY_EXCEEDED", "The confirmation would take the consultant past full capacity.")
    if assignment["category"] == "BILLABLE":
        rate = effective_rate(demand)
        margin = q2(Decimal(100) * (rate - assignment["cost_rate_usd_per_hour"]) / rate)
        if margin < MARGIN_FLOOR_PCT:
            fail("ERR_MARGIN_FLOOR_BREACH", "The confirmation would drive the margin below the floor.")
    assignment["status"] = "CONFIRMED"
    assignment["confirmed_on"] = today()
    assignment["bill_rate_usd_per_hour"] = (
        effective_rate(demand) if assignment["category"] == "BILLABLE" else Decimal("0.00")
    )
    bump(assignment)
    close_spell_after_confirm(consultant)
    bump(consultant)
    bump(demand)
    settle()
    return obj(serial.assignment(assignment))


@bp.post("/assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    begin("ResourceManager")
    assignment = need("assignments", assignment_id)
    payload = body(allowed=("reason",))
    if payload.get("reason") is not None:
        opt_str(payload, "reason", 1, 500)
    if assignment["status"] not in ("CONFIRMED", "ACTIVE"):
        fail("ERR_ASSIGNMENT_STATE_INVALID", "Only a CONFIRMED or ACTIVE assignment may be released.")
    if today() < assignment["start_date"]:
        fail("ERR_ASSIGNMENT_STATE_INVALID", "An assignment that has not started is cancelled, not released.")
    assignment["status"] = "RELEASED"
    assignment["released_on"] = today()
    bump(assignment)
    consultant = db.get("consultants", assignment["consultant_id"])
    reopen_spell_if_benched(consultant)
    bump(consultant)
    demand = db.get("demand_opportunities", assignment["demand_opportunity_id"])
    if demand is not None:
        bump(demand)
    settle()
    return obj(serial.assignment(assignment))


@bp.post("/assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    begin("ResourceManager")
    assignment = need("assignments", assignment_id)
    payload = body(allowed=("reason",))
    if payload.get("reason") is not None:
        opt_str(payload, "reason", 1, 500)
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_ASSIGNMENT_STATE_INVALID", "Only a PROPOSED or CONFIRMED assignment may be cancelled.")
    was_confirmed = assignment["status"] == "CONFIRMED"
    if was_confirmed and today() >= assignment["start_date"]:
        fail("ERR_ASSIGNMENT_STATE_INVALID", "A commitment that has started must be released, not cancelled.")
    assignment["status"] = "CANCELLED"
    bump(assignment)
    consultant = db.get("consultants", assignment["consultant_id"])
    if was_confirmed:
        reopen_spell_if_benched(consultant)
    bump(consultant)
    if was_confirmed:
        demand = db.get("demand_opportunities", assignment["demand_opportunity_id"])
        if demand is not None:
            bump(demand)
    settle()
    return obj(serial.assignment(assignment))
