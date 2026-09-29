"""Discount approvals, utilization periods, hiring forecasts and the logical
clock (PRD 3.7, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import serial
from derive import (
    DISCOUNT_HARD_CAP_PCT,
    apply_rate_cascade,
    availability,
    compute_forecast,
    discount_pass,
    level_target,
    period_buckets,
    periods_of,
)
from envelope import collection, empty, obj
from errors import bad_request, fail
from helpers import q2
from ops import need, now, settle, today
from reqctx import (
    GEOGRAPHIES,
    begin,
    body,
    filter_enum,
    filter_value,
    opt_dec,
    opt_enum,
    opt_str,
    pagination,
    present,
    req_date,
    req_dec,
    req_enum,
    req_id,
    req_instant,
    req_int,
    req_str,
    window,
)
from store import bump, db

bp = Blueprint("finance", __name__)

APPROVAL_READ_ROLES = ("SalesLead", "PracticePartner", "FinanceController")
APPROVAL_STATUSES = ("PENDING", "APPROVED", "REJECTED")
TIERS = ("NONE", "L1_PRACTICE_PARTNER", "L2_FINANCE")
TIER_ROLES = {
    "NONE": ("PracticePartner", "FinanceController"),
    "L1_PRACTICE_PARTNER": ("PracticePartner", "FinanceController"),
    "L2_FINANCE": ("FinanceController",),
}


def _discount_pct(standard, requested):
    return q2(Decimal(100) * (standard - requested) / standard)


@bp.post("/discount-approvals")
def create_discount_approval():
    ctx = begin("SalesLead")
    payload = body(
        allowed=(
            "demand_opportunity_id",
            "requested_rate_usd_per_hour",
            "expected_opportunity_version",
            "decision_note",
        ),
        required=(
            "demand_opportunity_id",
            "requested_rate_usd_per_hour",
            "expected_opportunity_version",
        ),
    )
    demand_id = req_id(payload, "demand_opportunity_id")
    requested = req_dec(payload, "requested_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    expected = req_int(payload, "expected_opportunity_version", 1)
    note = opt_str(payload, "decision_note", 1, 280)
    demand = need("demand_opportunities", demand_id)
    if demand["version"] != expected:
        fail("ERR_STALE_OPPORTUNITY_VERSION", "The demand has moved on since that version was read.")
    if demand["pipeline_status"] not in ("QUALIFYING", "QUALIFIED"):
        fail("ERR_OPPORTUNITY_STATE_INVALID", "A closed demand takes no discount request.")
    standard = demand["standard_rate_usd_per_hour"]
    if requested > standard:
        fail("ERR_RATE_ABOVE_STANDARD", "A discount may not price above the standard rate.")
    if _discount_pct(standard, requested) > DISCOUNT_HARD_CAP_PCT:
        fail("ERR_DISCOUNT_CAP_EXCEEDED", "No role may approve a discount past the hard cap.")
    row = db.new_row("discount_approvals")
    row.update(
        {
            "demand_opportunity_id": demand["id"],
            "requested_rate_usd_per_hour": requested,
            "standard_rate_usd_per_hour": standard,
            "status": "PENDING",
            "requested_by_user_id": ctx.user_id,
            "decided_by_user_id": None,
            "decision_note": note,
            "revision_count": 0,
        }
    )
    auto_approved = discount_pass(row, demand)
    db.insert("discount_approvals", row)
    if auto_approved:
        apply_rate_cascade(demand, row["requested_rate_usd_per_hour"])
    bump(demand)
    return obj(serial.discount_approval(row), 201)


@bp.get("/discount-approvals")
def list_discount_approvals():
    begin(*APPROVAL_READ_ROLES)
    limit, offset = pagination()
    demand_id = filter_value("demand_opportunity_id")
    status = filter_enum("status", APPROVAL_STATUSES)
    tier = filter_enum("required_tier", TIERS)
    rows = db.all("discount_approvals")
    if demand_id is not None:
        rows = [r for r in rows if r["demand_opportunity_id"] == demand_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["required_tier"] == tier]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/discount-approvals/<approval_id>")
def read_discount_approval(approval_id):
    begin(*APPROVAL_READ_ROLES)
    return obj(serial.discount_approval(need("discount_approvals", approval_id)))


@bp.post("/discount-approvals/<approval_id>/decide")
def decide_discount_approval(approval_id):
    ctx = begin("PracticePartner", "FinanceController")
    approval = need("discount_approvals", approval_id)
    payload = body(allowed=("decision", "decision_note"), required=("decision",))
    decision = req_enum(payload, "decision", ("APPROVED", "REJECTED"))
    note = opt_str(payload, "decision_note", 1, 280)
    if approval["status"] != "PENDING":
        fail("ERR_APPROVAL_STATE_INVALID", "Only a PENDING approval may be decided.")
    if ctx.user_id == approval["requested_by_user_id"]:
        fail("ERR_SELF_APPROVAL_FORBIDDEN", "The requester may not decide their own discount.")
    if ctx.role not in TIER_ROLES[approval["required_tier"]]:
        fail("ERR_APPROVAL_TIER_INSUFFICIENT", "This role does not satisfy the required approval tier.")
    if approval["discount_pct"] > DISCOUNT_HARD_CAP_PCT:
        fail("ERR_DISCOUNT_CAP_EXCEEDED", "No role may approve a discount past the hard cap.")
    approval["status"] = decision
    approval["decided_by_user_id"] = ctx.user_id
    if note is not None:
        approval["decision_note"] = note
    bump(approval)
    if decision == "APPROVED":
        demand = db.get("demand_opportunities", approval["demand_opportunity_id"])
        apply_rate_cascade(demand, approval["requested_rate_usd_per_hour"])
        bump(demand)
    return obj(serial.discount_approval(approval))


@bp.post("/discount-approvals/<approval_id>/revise")
def revise_discount_approval(approval_id):
    ctx = begin("SalesLead")
    approval = need("discount_approvals", approval_id)
    payload = body(
        allowed=("requested_rate_usd_per_hour", "decision_note"),
        required=("requested_rate_usd_per_hour",),
    )
    requested = req_dec(payload, "requested_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    note = opt_str(payload, "decision_note", 1, 280)
    if approval["status"] != "REJECTED":
        fail("ERR_APPROVAL_STATE_INVALID", "Only a REJECTED approval may be revised.")
    demand = db.get("demand_opportunities", approval["demand_opportunity_id"])
    if requested > demand["standard_rate_usd_per_hour"]:
        fail("ERR_RATE_ABOVE_STANDARD", "A discount may not price above the standard rate.")
    if _discount_pct(approval["standard_rate_usd_per_hour"], requested) > DISCOUNT_HARD_CAP_PCT:
        fail("ERR_DISCOUNT_CAP_EXCEEDED", "No role may approve a discount past the hard cap.")
    if requested <= approval["requested_rate_usd_per_hour"]:
        fail("ERR_REVISION_NOT_HIGHER", "A revision must concede ground on price.")
    approval["requested_rate_usd_per_hour"] = requested
    approval["status"] = "PENDING"
    approval["revision_count"] = approval["revision_count"] + 1
    approval["decided_by_user_id"] = None
    approval["requested_by_user_id"] = ctx.user_id
    if note is not None:
        approval["decision_note"] = note
    discount_pass(approval, demand, steps=6)
    bump(approval)
    return obj(serial.discount_approval(approval))


# ------------------------------------------------------------ utilization periods
PERIOD_READ_ROLES = ("FinanceController", "ResourceManager", "PracticePartner", "Consultant")
PERIOD_STATUSES = ("OPEN", "CLOSED")


def _period_of(consultant, period_id):
    period = need("utilization_periods", period_id)
    if period["consultant_id"] != consultant["id"]:
        fail("ERR_PERIOD_NOT_FOUND", "That period does not belong to this consultant.")
    return period


@bp.post("/consultants/<consultant_id>/utilization-periods")
def open_period(consultant_id):
    begin("FinanceController")
    consultant = need("consultants", consultant_id)
    payload = body(
        allowed=("period_start_on", "period_end_on", "holiday_hours"),
        required=("period_start_on", "period_end_on"),
    )
    start = req_date(payload, "period_start_on")
    end = req_date(payload, "period_end_on")
    if end < start:
        bad_request("Field 'period_end_on' must be on or after 'period_start_on'.")
    holiday = opt_dec(payload, "holiday_hours", Decimal("0.00"), Decimal("2000.00"), 2, Decimal("0.00"))
    if availability(consultant) == "SEPARATED":
        fail("ERR_CONSULTANT_SEPARATED", "A separated consultant takes no new measurement period.")
    for other in periods_of(consultant["id"]):
        if start <= other["period_end_on"] and other["period_start_on"] <= end:
            fail("ERR_PERIOD_OVERLAP", "Utilization periods of one consultant may not overlap.")
    row = db.new_row("utilization_periods")
    row.update(
        {
            "consultant_id": consultant["id"],
            "period_start_on": start,
            "period_end_on": end,
            "holiday_hours": holiday,
            "target_utilization_pct": level_target(consultant)["target_utilization_pct"],
            "status": "OPEN",
            "_snapshot": None,
        }
    )
    db.insert("utilization_periods", row)
    return obj(serial.utilization_period(row), 201)


@bp.get("/consultants/<consultant_id>/utilization-periods")
def list_periods(consultant_id):
    ctx = begin(*PERIOD_READ_ROLES)
    consultant = need("consultants", consultant_id)
    if ctx.is_consultant and ctx.user_id != consultant["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A consultant may read only their own periods.")
    limit, offset = pagination()
    status = filter_enum("status", PERIOD_STATUSES)
    rows = periods_of(consultant["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/consultants/<consultant_id>/utilization-periods/<period_id>")
def read_period(consultant_id, period_id):
    ctx = begin(*PERIOD_READ_ROLES)
    consultant = need("consultants", consultant_id)
    period = _period_of(consultant, period_id)
    if ctx.is_consultant and ctx.user_id != consultant["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A consultant may read only their own periods.")
    return obj(serial.utilization_period(period))


@bp.post("/consultants/<consultant_id>/utilization-periods/<period_id>/close")
def close_period(consultant_id, period_id):
    begin("FinanceController")
    consultant = need("consultants", consultant_id)
    period = _period_of(consultant, period_id)
    body(allowed=())
    if period["status"] != "OPEN":
        fail("ERR_PERIOD_STATE_INVALID", "Only an OPEN period may be closed.")
    if period["period_end_on"] >= today():
        fail("ERR_PERIOD_STATE_INVALID", "A period that has not finished may not be closed.")
    buckets = period_buckets(period)
    if buckets["hour_overallocated"]:
        fail("ERR_HOUR_OVERALLOCATION", "An over-allocated period may not be closed.")
    period["_snapshot"] = buckets
    period["status"] = "CLOSED"
    bump(period)
    return obj(serial.utilization_period(period))


# ----------------------------------------------------------- hiring forecasts
FORECAST_READ_ROLES = ("FinanceController", "PracticePartner", "ResourceManager")
BASES = ("WEIGHTED", "COMMITTED")


@bp.post("/hiring-forecasts")
def generate_forecast():
    begin("FinanceController", "PracticePartner")
    payload = body(
        allowed=("skill_code", "geography_code", "horizon_start_on", "horizon_end_on", "basis"),
        required=("skill_code", "geography_code", "horizon_start_on", "horizon_end_on"),
    )
    skill_code = req_str(payload, "skill_code", 1, 30)
    geography = req_enum(payload, "geography_code", GEOGRAPHIES)
    start = req_date(payload, "horizon_start_on")
    end = req_date(payload, "horizon_end_on")
    if end < start:
        bad_request("Field 'horizon_end_on' must be on or after 'horizon_start_on'.")
    basis = opt_enum(payload, "basis", BASES, "WEIGHTED")
    if not any(skill["code"] == skill_code for skill in db.all("skills")):
        fail("ERR_GEOGRAPHY_MISMATCH", "No registered skill carries that code.")
    row = db.new_row("hiring_forecasts", versioned=False)
    row.update(
        {
            "skill_code": skill_code,
            "geography_code": geography,
            "horizon_start_on": start,
            "horizon_end_on": end,
            "basis": basis,
            "generated_at": now(),
        }
    )
    row.update(compute_forecast(skill_code, geography, start, end, basis))
    db.insert("hiring_forecasts", row)
    return obj(serial.hiring_forecast(row), 201)


@bp.get("/hiring-forecasts")
def list_forecasts():
    begin(*FORECAST_READ_ROLES)
    limit, offset = pagination()
    skill_code = filter_value("skill_code")
    geography = filter_enum("geography_code", GEOGRAPHIES)
    basis = filter_enum("basis", BASES)
    rows = db.all("hiring_forecasts")
    if skill_code is not None:
        rows = [r for r in rows if r["skill_code"] == skill_code]
    if geography is not None:
        rows = [r for r in rows if r["geography_code"] == geography]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/hiring-forecasts/<forecast_id>")
def read_forecast(forecast_id):
    begin(*FORECAST_READ_ROLES)
    return obj(serial.hiring_forecast(need("hiring_forecasts", forecast_id)))


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    begin("ResourceManager", "PracticePartner", "FinanceController", "SalesLead")
    payload = body(allowed=("current_utc",), required=("current_utc",))
    db.clock = req_instant(payload, "current_utc")
    return empty(200)
