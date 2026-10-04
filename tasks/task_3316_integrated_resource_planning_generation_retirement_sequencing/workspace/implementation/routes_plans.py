"""ResourcePlan routes: CRUD, lifecycle transitions, commission review, reopen."""

from datetime import date, timedelta

from flask import Blueprint, request

from calculations import (
    CYCLE_DEADLINE_MONTH_DAY, COMMENT_WINDOW_DAYS, REOPEN_LIMIT,
)
from db import store
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NO_PREFERRED_PORTFOLIO,
    ERR_PLAN_MISSING_BASE_FORECAST, ERR_PLAN_MISSING_PORTFOLIO,
    ERR_PLAN_NOT_FOUND, ERR_PLAN_NOT_UNDER_REVIEW, ERR_PLAN_REOPEN_LIMIT,
    ERR_RELIABILITY_NOT_MET, ERR_STALE_PLAN_VERSION,
    ERR_CYCLE_DEADLINE_MISSED, ERR_COMMENT_WINDOW_OPEN,
    raise_error,
)
from helpers import (
    body, get_int, get_str, paginate, parse_pagination, require_fields,
    stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import plan_view

bp = Blueprint("plans", __name__)

ALL_ROLES = ("UtilityPlanner", "Commissioner", "Intervener",
             "PublicCommenter", "PlatformAdmin")

PLAN_STATUSES = {
    "DRAFT", "OPEN_FOR_COMMENT", "UNDER_REVIEW", "APPROVED",
    "APPROVED_WITH_CONDITIONS", "REJECTED", "SUPERSEDED",
}


def get_plan_or_404(plan_id: str) -> dict:
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_error(ERR_PLAN_NOT_FOUND, f"Plan {plan_id} not found")
    return plan


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@bp.route("/plans", methods=["POST"])
@require_roles("UtilityPlanner")
def create_plan(user_id, role):
    payload = body()
    require_fields(payload, "plan_name", "cycle_year", "planning_horizon_years")
    plan_name = get_str(payload, "plan_name")
    cycle_year = get_int(payload, "cycle_year")
    horizon = get_int(payload, "planning_horizon_years")
    if horizon < 10:
        raise_error(ERR_INVALID_REQUEST, "planning_horizon_years must be >= 10")
    plan = stamp_new({
        "plan_name": plan_name,
        "cycle_year": cycle_year,
        "planning_horizon_years": horizon,
        "status": "DRAFT",
        "comment_window_opens_on": None,
        "comment_window_closes_on": None,
        "submitted_on": None,
        "approved_snapshot_id": None,
        "preferred_portfolio_id": None,
        "reopen_count": 0,
    })
    store.plans[plan["id"]] = plan
    return success_object(plan_view(plan), 201)


@bp.route("/plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plans(user_id, role):
    limit, offset = parse_pagination()
    args = request.args
    items = list(store.plans.values())
    if "status" in args:
        items = [p for p in items if p["status"] == args["status"]]
    if "cycle_year" in args:
        try:
            cy = int(args["cycle_year"])
        except ValueError:
            raise_error(ERR_INVALID_REQUEST, "cycle_year must be an integer")
        items = [p for p in items if p["cycle_year"] == cy]
    if "approved_snapshot_id" in args:
        items = [p for p in items if p.get("approved_snapshot_id") == args["approved_snapshot_id"]]
    if "preferred_portfolio_id" in args:
        items = [p for p in items if p.get("preferred_portfolio_id") == args["preferred_portfolio_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([plan_view(p) for p in page], limit, offset, total)


@bp.route("/plans/<planId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan(user_id, role, planId):
    plan = get_plan_or_404(planId)
    return success_object(plan_view(plan), 200)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

@bp.route("/plans/<planId>/open-comment", methods=["POST"])
@require_roles("UtilityPlanner")
def open_comment(user_id, role, planId):
    plan = get_plan_or_404(planId)
    if plan["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Plan is not DRAFT")
    # Business gates (priority 9): base forecast, portfolio, then deadline (6).
    has_base = any(
        f["plan_id"] == plan["id"] and f["scenario_tag"] == "BASE"
        for f in store.forecasts.values()
    )
    if not has_base:
        raise_error(ERR_PLAN_MISSING_BASE_FORECAST, "Plan has no BASE forecast row")
    has_portfolio = any(pf["plan_id"] == plan["id"] for pf in store.portfolios.values())
    if not has_portfolio:
        raise_error(ERR_PLAN_MISSING_PORTFOLIO, "Plan has no portfolio")
    # Cycle deadline: submitted_on must be on or before Sept 1 of cycle_year.
    clock_date = store.clock.now().date()
    deadline = date.fromisoformat(f"{plan['cycle_year']}-{CYCLE_DEADLINE_MONTH_DAY}")
    if clock_date > deadline:
        raise_error(ERR_CYCLE_DEADLINE_MISSED,
                    "submitted_on would be after September 1 of the cycle year")
    opens = clock_date
    closes = opens + timedelta(days=COMMENT_WINDOW_DAYS)
    plan["status"] = "OPEN_FOR_COMMENT"
    plan["comment_window_opens_on"] = opens.isoformat()
    plan["comment_window_closes_on"] = closes.isoformat()
    plan["submitted_on"] = opens.isoformat()
    for f in store.forecasts.values():
        if f["plan_id"] == plan["id"]:
            f["locked"] = True
    touch(plan)
    return success_object(plan_view(plan), 200)


@bp.route("/plans/<planId>/submit-for-review", methods=["POST"])
@require_roles("UtilityPlanner")
def submit_for_review(user_id, role, planId):
    plan = get_plan_or_404(planId)
    if plan["status"] != "OPEN_FOR_COMMENT":
        raise_error(ERR_INVALID_STATE, "Plan is not OPEN_FOR_COMMENT")
    clock_date = store.clock.now().date()
    closes = date.fromisoformat(plan["comment_window_closes_on"])
    if clock_date < closes:
        raise_error(ERR_COMMENT_WINDOW_OPEN,
                    "Comment window has not closed yet")
    preferred = [pf for pf in store.portfolios.values()
                 if pf["plan_id"] == plan["id"] and pf.get("preferred_flag")]
    if not preferred:
        raise_error(ERR_NO_PREFERRED_PORTFOLIO,
                    "Plan has no preferred portfolio")
    for pf in store.portfolios.values():
        if pf["plan_id"] == plan["id"] and pf["status"] == "DRAFT":
            pf["status"] = "FROZEN"
            touch(pf)
    plan["preferred_portfolio_id"] = preferred[0]["id"]
    plan["status"] = "UNDER_REVIEW"
    touch(plan)
    return success_object(plan_view(plan), 200)


@bp.route("/plans/<planId>/commission-review", methods=["POST"])
@require_roles("Commissioner")
def commission_review(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "decision", "expected_plan_version")
    decision = payload["decision"]
    if decision not in ("APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE, APPROVE_WITH_CONDITIONS, or REJECT")
    expected = payload["expected_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_plan_version must be an integer")
    conditions_payload = payload.get("conditions", [])
    if decision == "APPROVE_WITH_CONDITIONS":
        if not isinstance(conditions_payload, list) or len(conditions_payload) == 0:
            raise_error(ERR_INVALID_REQUEST,
                        "conditions must be a non-empty array for APPROVE_WITH_CONDITIONS")
    # OCC (priority 4)
    if expected != plan["version"]:
        raise_error(ERR_STALE_PLAN_VERSION,
                    "expected_plan_version does not match the current plan version")
    # State gate (priority 5)
    if plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_PLAN_NOT_UNDER_REVIEW, "Plan is not UNDER_REVIEW")
    # Business gate (priority 9): reliability on approving decisions.
    if decision in ("APPROVE", "APPROVE_WITH_CONDITIONS"):
        pref_id = plan.get("preferred_portfolio_id")
        reliable = any(
            s["portfolio_id"] == pref_id
            and s.get("meets_requirement") is True
            and not s.get("retire_flagged", False)
            for s in store.snapshots.values()
        )
        if not reliable:
            raise_error(ERR_RELIABILITY_NOT_MET,
                        "Preferred portfolio has no passing, unflagged snapshot")
    # Execute the decision.
    if decision == "REJECT":
        plan["status"] = "REJECTED"
        touch(plan)
        return success_object(plan_view(plan), 200)
    # Approving decisions.
    pref_id = plan["preferred_portfolio_id"]
    snaps = [s for s in store.snapshots.values() if s["portfolio_id"] == pref_id]
    snaps.sort(key=lambda s: s["created_at"], reverse=True)
    if snaps:
        latest_ts = snaps[0]["created_at"]
        tied = [s for s in snaps if s["created_at"] == latest_ts]
        if len(tied) > 1:
            raise_error(ERR_INVALID_REQUEST,
                        "Ambiguous most-recent snapshot (created_at tie)")
        plan["approved_snapshot_id"] = snaps[0]["id"]
    plan["status"] = "APPROVED" if decision == "APPROVE" else "APPROVED_WITH_CONDITIONS"
    if decision == "APPROVE_WITH_CONDITIONS":
        for elem in conditions_payload:
            if not isinstance(elem, dict):
                raise_error(ERR_INVALID_REQUEST, "conditions entries must be objects")
            desc = elem.get("description")
            req_mw = elem.get("required_procurement_mw")
            if not isinstance(desc, str) or not desc.strip():
                raise_error(ERR_INVALID_REQUEST, "condition description must be a non-empty string")
            if isinstance(req_mw, bool) or not isinstance(req_mw, (int, float)) or req_mw < 0:
                raise_error(ERR_INVALID_REQUEST, "required_procurement_mw must be >= 0")
            cond = stamp_new({
                "plan_id": plan["id"],
                "description": desc,
                "required_procurement_mw": req_mw,
                "status": "OPEN",
            })
            store.conditions[cond["id"]] = cond
    touch(plan)
    # Supersede cascade: other approved plans with the same cycle_year.
    for other in store.plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["cycle_year"] == plan["cycle_year"] and other["status"] in (
                "APPROVED", "APPROVED_WITH_CONDITIONS"):
            other["status"] = "SUPERSEDED"
            touch(other)
    return success_object(plan_view(plan), 200)


@bp.route("/plans/<planId>/reopen", methods=["POST"])
@require_roles("UtilityPlanner")
def reopen_plan(user_id, role, planId):
    plan = get_plan_or_404(planId)
    if plan["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE, "Plan is not REJECTED")
    if plan["reopen_count"] >= REOPEN_LIMIT:
        raise_error(ERR_PLAN_REOPEN_LIMIT, "Plan reopen limit reached")
    plan["reopen_count"] += 1
    plan["status"] = "DRAFT"
    plan["preferred_portfolio_id"] = None
    plan["approved_snapshot_id"] = None
    plan["comment_window_opens_on"] = None
    plan["comment_window_closes_on"] = None
    plan["submitted_on"] = None
    for pf in store.portfolios.values():
        if pf["plan_id"] == plan["id"] and pf["status"] == "FROZEN":
            pf["status"] = "DRAFT"
            touch(pf)
    for f in store.forecasts.values():
        if f["plan_id"] == plan["id"]:
            f["locked"] = False
    touch(plan)
    return success_object(plan_view(plan), 200)
