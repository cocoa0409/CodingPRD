"""CategoryAnalysis: advisory submissions and the retailer decide step,
including the data-governance boundary on competitor data."""

from flask import Blueprint, request

import validation as V
from auth import (
    ALL_ROLES,
    ROLE_CATEGORY_ADVISOR,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import ANALYSIS_DECISIONS, ANALYSIS_TERMINAL
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch

bp = Blueprint("analyses", __name__)


@bp.post("/jbp/plans/<plan_id>/category-analyses")
def create_analysis(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_CATEGORY_ADVISOR])
    data = V.body()
    V.check_undeclared(
        data,
        {
            "title",
            "period_label",
            "includes_competitor_data",
            "total_category_growth_pct",
            "manufacturer_share_pct",
        },
    )
    title = V.as_str(V.require(data, "title"), "title")
    period_label = V.as_str(V.require(data, "period_label"), "period_label")
    includes = V.as_bool(data.get("includes_competitor_data", False), "includes_competitor_data")
    total_growth = V.as_num(
        V.require(data, "total_category_growth_pct"), "total_category_growth_pct"
    )
    share = V.as_num(V.require(data, "manufacturer_share_pct"), "manufacturer_share_pct")
    if share < 0 or share > 100:
        err("ERR_VALIDATION", "manufacturer_share_pct must be in [0, 100]")
    plan = plan_or_404(plan_id)  # 6
    # priority 18: data-governance boundary
    if includes:
        category = STORE["categories"].get(plan["category_id"])
        if category is not None and category["advisory_scope"] != "FULL_CATEGORY":
            err(
                "ERR_GOVERNANCE_BOUNDARY",
                "competitor data requires category advisory_scope FULL_CATEGORY",
            )
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "title": title,
        "period_label": period_label,
        "includes_competitor_data": includes,
        "total_category_growth_pct": total_growth,
        "manufacturer_share_pct": share,
        "competitor_share_pct": 100 - share,
        "status": "SUBMITTED",
    }
    stamp_new(rec)
    STORE["analyses"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.get("/jbp/plans/<plan_id>/category-analyses")
def list_analyses(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [a for a in by_seq(STORE["analyses"].values()) if a["plan_id"] == plan_id]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(a) for a in page], limit, offset, total)


@bp.post("/jbp/category-analyses/<analysis_id>/decide")
def decide_analysis(analysis_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    analysis = STORE["analyses"].get(analysis_id)
    plan = STORE["plans"].get(analysis["plan_id"]) if analysis is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"decision"})
    decision = V.as_enum(V.require(data, "decision"), "decision", ANALYSIS_DECISIONS)  # 4
    if analysis is None:
        err("ERR_RESOURCE_NOT_FOUND", "category analysis not found")  # 6
    if analysis["status"] in ANALYSIS_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "analysis is terminal")  # 8
    analysis["status"] = "ACCEPTED" if decision == "ACCEPT" else "RETURNED"
    touch(analysis)
    return success(public(analysis))
