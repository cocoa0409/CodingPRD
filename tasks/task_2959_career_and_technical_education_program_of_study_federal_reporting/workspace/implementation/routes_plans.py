"""Improvement-plan routes and the sanction-lifting cascade (PRD sec 3.9)."""
from flask import Blueprint

import resolve
import serialize
import services
import shape
from auth import endpoint
from envelope import created, listing, ok, page
from errors import ApiError
from store import (MAX_PLAN_REVISION_ROUNDS, MIN_PLAN_MILESTONES, PLAN_STATUSES,
                   clock_stamp, db, stamp_new, touch)

bp = Blueprint("plans", __name__)
DIRECTOR = ("CteDirector",)
REVIEWER = ("StateComplianceReviewer",)
READERS = ("CteDirector", "StateComplianceReviewer", "GrantFiscalOfficer")


def _check_funding(expenditure_id, indicator):
    """Priority 32 -- re-evaluated at draft and again at every submit."""
    if expenditure_id is None:
        return
    expenditure = db.expenditures.get(expenditure_id)
    if (expenditure is None
            or expenditure["status"] not in ("CERTIFIED", "OBLIGATED")
            or expenditure["pos_id"] != indicator["pos_id"]):
        raise ApiError("ERR_PLAN_FUNDING_INVALID",
                       "The funding expenditure must be CERTIFIED or OBLIGATED "
                       "and charged to the same program of study.")


# ------------------------------------------------------------------ reads
@bp.get("/cte/improvement-plans")
@endpoint(READERS)
def list_plans():
    limit, offset = shape.pagination()
    indicator_id = shape.filter_str("performance_indicator_id")
    funding_id = shape.filter_str("funding_expenditure_id")
    status = shape.filter_enum("status", PLAN_STATUSES)
    rows = list(db.plans.values())
    if indicator_id is not None:
        rows = [r for r in rows if r["performance_indicator_id"] == indicator_id]
    if funding_id is not None:
        rows = [r for r in rows if r["funding_expenditure_id"] == funding_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.plan(r) for r in window], limit, offset, total)


@bp.get("/cte/improvement-plans/<plan_id>")
@endpoint(READERS)
def get_plan(plan_id):
    return ok(serialize.plan(resolve.plan(plan_id)))


# ------------------------------------------------------------------ writes
@bp.post("/cte/performance-indicators/<indicator_id>/improvement-plans")
@endpoint(DIRECTOR)
def draft_plan(indicator_id):
    data = shape.body()
    milestones = shape.req_milestones(data, "milestones")
    funding_id = shape.opt_string(data, "funding_expenditure_id")
    indicator = resolve.indicator(indicator_id)
    if funding_id is not None:
        resolve.expenditure(funding_id)
    if indicator["status"] != "IMPROVEMENT_REQUIRED":
        raise ApiError("ERR_INVALID_INDICATOR_STATE",
                       "An improvement plan may only be drafted for an indicator "
                       "in IMPROVEMENT_REQUIRED.")
    _check_funding(funding_id, indicator)
    plan = stamp_new({
        "performance_indicator_id": indicator_id,
        "funding_expenditure_id": funding_id,
        "milestones": milestones,
        "revision_round": 0,
        "status": "DRAFT",
        "return_reasons": [],
        "submitted_at": None,
        "accepted_at": None,
    })
    db.plans[plan["id"]] = plan
    return created(serialize.plan(plan))


@bp.post("/cte/improvement-plans/<plan_id>/submit")
@endpoint(DIRECTOR)
def submit_plan(plan_id):
    data = shape.body()
    shape.opt_string(data, "submission_note")
    plan = resolve.plan(plan_id)
    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Plan status %s does not declare a transition to SUBMITTED."
                       % plan["status"])
    if len(plan["milestones"]) < MIN_PLAN_MILESTONES:
        raise ApiError("ERR_MILESTONES_INSUFFICIENT",
                       "An improvement plan requires at least 3 milestones.")
    indicator = db.indicators.get(plan["performance_indicator_id"])
    _check_funding(plan["funding_expenditure_id"], indicator)
    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = clock_stamp()
    touch(plan)
    return ok(serialize.plan(plan))


@bp.post("/cte/improvement-plans/<plan_id>/return")
@endpoint(REVIEWER)
def return_plan(plan_id):
    data = shape.body()
    return_reason = shape.req_string(data, "return_reason")
    plan = resolve.plan(plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Plan status %s does not admit a return ruling."
                       % plan["status"])
    plan["return_reasons"].append(return_reason)
    plan["revision_round"] = int(plan["revision_round"]) + 1
    terminal = int(plan["revision_round"]) >= MAX_PLAN_REVISION_ROUNDS
    plan["status"] = "REJECTED_FINAL" if terminal else "RETURNED"
    touch(plan)
    if terminal:
        indicator = db.indicators.get(plan["performance_indicator_id"])
        if indicator is not None and indicator["status"] == "IMPROVEMENT_REQUIRED":
            services.sanction_indicator(indicator)
    return ok(serialize.plan(plan))


@bp.post("/cte/improvement-plans/<plan_id>/accept")
@endpoint(REVIEWER)
def accept_plan(plan_id):
    data = shape.body()
    shape.opt_string(data, "acceptance_note")
    plan = resolve.plan(plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Plan status %s does not declare a transition to ACCEPTED."
                       % plan["status"])
    indicator = db.indicators.get(plan["performance_indicator_id"])
    if indicator is None or indicator["status"] != "IMPROVEMENT_REQUIRED":
        raise ApiError("ERR_INVALID_INDICATOR_STATE",
                       "The plan's parent indicator must be in "
                       "IMPROVEMENT_REQUIRED to accept the plan.")
    plan["status"] = "ACCEPTED"
    plan["accepted_at"] = clock_stamp()
    touch(plan)
    services.accept_plan_cascade(indicator)
    return ok(serialize.plan(plan))
