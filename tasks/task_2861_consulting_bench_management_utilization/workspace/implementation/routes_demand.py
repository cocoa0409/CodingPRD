"""The demand pipeline, the staffing branch and the auto-staff selector
(PRD 3.3, 3.4 and the selector half of 3.5)."""
from decimal import Decimal

from flask import Blueprint

import serial
from derive import (
    assignments_on,
    auto_staff_candidates,
    coverage,
    effective_rate,
    match_score,
    placements_on,
    rank_candidates,
    realization,
)
from envelope import collection, obj
from errors import bad_request, fail
from helpers import day_after
from ops import need, reopen_spell_if_benched, settle, today
from reqctx import (
    begin,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    req_str,
    pagination,
    req_code,
    req_date,
    req_dec,
    req_enum,
    req_id,
    req_int,
    window,
)
from store import bump, db

bp = Blueprint("demand", __name__)

READ_ROLES = ("SalesLead", "ResourceManager", "PracticePartner", "FinanceController")
PIPELINE = ("QUALIFYING", "QUALIFIED", "CLOSED_WON", "CLOSED_LOST")
STAFFING_STATUS = ("UNSTAFFED", "INTERNAL_STAFFING", "EXTERNAL_SOURCING", "PARTIALLY_COVERED", "COVERED")
MODES = ("INTERNAL", "EXTERNAL")


def new_assignment(consultant, demand, allocation, start, end, category, score):
    row = db.new_row("assignments")
    row.update(
        {
            "consultant_id": consultant["id"],
            "demand_opportunity_id": demand["id"],
            "allocation_pct": allocation,
            "start_date": start,
            "end_date": end,
            "category": category,
            "bill_rate_usd_per_hour": effective_rate(demand) if category == "BILLABLE" else Decimal("0.00"),
            "cost_rate_usd_per_hour": consultant["cost_rate_usd_per_hour"],
            "match_score": score,
            "status": "PROPOSED",
            "confirmed_on": None,
            "activated_on": None,
            "released_on": None,
        }
    )
    return db.insert("assignments", row)


@bp.post("/demand-opportunities")
def register_demand():
    begin("SalesLead")
    payload = body(
        allowed=(
            "client_name",
            "practice_group_id",
            "required_skill_id",
            "min_proficiency_level",
            "required_fte",
            "win_probability_pct",
            "start_date",
            "end_date",
            "industry_code",
            "onsite_nights_per_week",
            "is_international",
            "standard_rate_usd_per_hour",
            "requested_rate_usd_per_hour",
        ),
        required=(
            "client_name",
            "practice_group_id",
            "required_skill_id",
            "min_proficiency_level",
            "required_fte",
            "win_probability_pct",
            "start_date",
            "end_date",
            "industry_code",
            "onsite_nights_per_week",
            "standard_rate_usd_per_hour",
            "requested_rate_usd_per_hour",
        ),
    )
    client_name = req_str(payload, "client_name", 1, 120)
    group_id = req_id(payload, "practice_group_id")
    skill_id = req_id(payload, "required_skill_id")
    min_level = req_int(payload, "min_proficiency_level", 1, 5)
    required_fte = req_dec(payload, "required_fte", Decimal("0.25"), Decimal("20.00"))
    probability = req_int(payload, "win_probability_pct", 0, 100)
    start = req_date(payload, "start_date")
    end = req_date(payload, "end_date")
    if end < start:
        bad_request("Field 'end_date' must fall on or after 'start_date'.")
    industry_code = req_code(payload, "industry_code")
    onsite = req_int(payload, "onsite_nights_per_week", 0, 5)
    international = opt_bool(payload, "is_international", False)
    standard_rate = req_dec(payload, "standard_rate_usd_per_hour", Decimal("1.00"), Decimal("5000.00"))
    requested_rate = req_dec(payload, "requested_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    need("practice_groups", group_id)
    skill = need("skills", skill_id)
    if skill["retired"]:
        fail("ERR_SKILL_RETIRED", "That skill is retired and may not be named by a new demand.")
    if requested_rate > standard_rate:
        fail("ERR_RATE_ABOVE_STANDARD", "The requested rate may not exceed the standard rate.")
    row = db.new_row("demand_opportunities")
    row.update(
        {
            "client_name": client_name,
            "practice_group_id": group_id,
            "required_skill_id": skill_id,
            "min_proficiency_level": min_level,
            "required_fte": required_fte,
            "win_probability_pct": probability,
            "start_date": start,
            "end_date": end,
            "industry_code": industry_code,
            "onsite_nights_per_week": onsite,
            "is_international": international,
            "standard_rate_usd_per_hour": standard_rate,
            "requested_rate_usd_per_hour": requested_rate,
            "approved_rate_usd_per_hour": None,
            "pipeline_status": "QUALIFYING",
            "staffing_mode": None,
            "closed_outcome": None,
        }
    )
    db.insert("demand_opportunities", row)
    return obj(serial.demand(row), 201)


@bp.get("/demand-opportunities")
def list_demands():
    begin(*READ_ROLES)
    limit, offset = pagination()
    group_id = filter_value("practice_group_id")
    skill_id = filter_value("required_skill_id")
    pipeline = filter_enum("pipeline_status", PIPELINE)
    staffing_status = filter_enum("staffing_status", STAFFING_STATUS)
    mode = filter_enum("staffing_mode", MODES)
    rows = db.all("demand_opportunities")
    if group_id is not None:
        rows = [r for r in rows if r["practice_group_id"] == group_id]
    if skill_id is not None:
        rows = [r for r in rows if r["required_skill_id"] == skill_id]
    if pipeline is not None:
        rows = [r for r in rows if r["pipeline_status"] == pipeline]
    if mode is not None:
        rows = [r for r in rows if r.get("staffing_mode") == mode]
    if staffing_status is not None:
        rows = [r for r in rows if coverage(r)["staffing_status"] == staffing_status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/demand-opportunities/<demand_id>")
def read_demand(demand_id):
    begin(*READ_ROLES)
    return obj(serial.demand(need("demand_opportunities", demand_id)))


@bp.post("/demand-opportunities/<demand_id>/qualify")
def qualify_demand(demand_id):
    begin("SalesLead")
    demand = need("demand_opportunities", demand_id)
    body(allowed=())
    if demand["pipeline_status"] != "QUALIFYING":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFYING demand may be qualified.")
    if demand["win_probability_pct"] < 25:
        fail("ERR_OPPORTUNITY_STATE_INVALID", "A demand below a 25 percent win probability may not be qualified.")
    skill = db.get("skills", demand["required_skill_id"])
    if skill is not None and skill["retired"]:
        fail("ERR_SKILL_RETIRED", "The demand's required skill has been retired.")
    demand["pipeline_status"] = "QUALIFIED"
    bump(demand)
    return obj(serial.demand(demand))


@bp.post("/demand-opportunities/<demand_id>/staffing-mode")
def choose_staffing_mode(demand_id):
    begin("ResourceManager")
    demand = need("demand_opportunities", demand_id)
    payload = body(allowed=("staffing_mode",), required=("staffing_mode",))
    mode = req_enum(payload, "staffing_mode", MODES)
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFIED demand may choose a staffing branch.")
    if demand.get("staffing_mode") is not None:
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The staffing branch has already been chosen.")
    demand["staffing_mode"] = mode
    bump(demand)
    return obj(serial.demand(demand))


@bp.post("/demand-opportunities/<demand_id>/close")
def close_demand(demand_id):
    begin("SalesLead")
    demand = need("demand_opportunities", demand_id)
    payload = body(allowed=("outcome", "note"), required=("outcome",))
    outcome = req_enum(payload, "outcome", ("WON", "LOST"))
    if payload.get("note") is not None:
        req_str(payload, "note", 1, 500)
    if outcome == "WON":
        if demand["pipeline_status"] != "QUALIFIED":
            fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFIED demand may be closed WON.")
        if coverage(demand)["staffing_status"] != "COVERED":
            fail("ERR_OPPORTUNITY_STATE_INVALID", "A demand must be COVERED before it may be closed WON.")
        if realization(demand)["margin_breach"]:
            fail("ERR_OPPORTUNITY_STATE_INVALID", "A demand breaching the margin floor may not be closed WON.")
        demand["pipeline_status"] = "CLOSED_WON"
        demand["closed_outcome"] = "WON"
        for assignment in assignments_on(demand["id"]):
            if assignment["status"] == "CONFIRMED":
                assignment["status"] = "ACTIVE"
                assignment["activated_on"] = today()
                bump(assignment)
        for placement in placements_on(demand["id"]):
            if placement["status"] == "APPROVED":
                placement["status"] = "ACTIVE"
                bump(placement)
        bump(demand)
        settle()
        return obj(serial.demand(demand))

    if demand["pipeline_status"] not in ("QUALIFYING", "QUALIFIED"):
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only an open demand may be closed LOST.")
    unwind = demand["pipeline_status"] == "QUALIFIED"
    demand["pipeline_status"] = "CLOSED_LOST"
    demand["closed_outcome"] = "LOST"
    if unwind:
        touched = []
        for assignment in assignments_on(demand["id"]):
            if assignment["status"] in ("PROPOSED", "CONFIRMED"):
                assignment["status"] = "CANCELLED"
                bump(assignment)
                touched.append(assignment["consultant_id"])
            elif assignment["status"] == "ACTIVE":
                assignment["status"] = "RELEASED"
                assignment["released_on"] = today()
                bump(assignment)
                touched.append(assignment["consultant_id"])
        for placement in placements_on(demand["id"]):
            if placement["status"] in ("REQUESTED", "APPROVED", "ACTIVE"):
                placement["status"] = "TERMINATED"
                placement["terminated_on"] = today()
                bump(placement)
        for consultant_id in dict.fromkeys(touched):
            consultant = db.get("consultants", consultant_id)
            if consultant is None:
                continue
            reopen_spell_if_benched(consultant)
            bump(consultant)
    bump(demand)
    settle()
    return obj(serial.demand(demand))


@bp.post("/demand-opportunities/<demand_id>/auto-staff")
def auto_staff(demand_id):
    begin("ResourceManager")
    demand = need("demand_opportunities", demand_id)
    body(allowed=())
    if demand["pipeline_status"] != "QUALIFIED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "Only a QUALIFIED demand may be auto-staffed.")
    if demand.get("staffing_mode") is None:
        fail("ERR_STAFFING_MODE_NOT_SET", "The demand has not chosen a staffing branch yet.")
    if demand["staffing_mode"] != "INTERNAL":
        fail("ERR_STAFFING_MODE_MISMATCH", "Auto-staffing applies only to an INTERNAL demand.")
    candidates = auto_staff_candidates(demand)
    if not candidates:
        fail("ERR_NO_ELIGIBLE_CONSULTANT", "No consultant satisfies the auto-staffing eligibility filter.")
    winner = rank_candidates(demand, candidates)[0]
    row = new_assignment(
        winner,
        demand,
        Decimal("100.00"),
        demand["start_date"],
        day_after(demand["end_date"]),
        "BILLABLE",
        match_score(winner, demand),
    )
    return obj(serial.assignment(row), 201)
