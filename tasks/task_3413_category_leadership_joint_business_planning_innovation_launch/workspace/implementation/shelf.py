"""ShelfRecommendation: the API's single OCC-guarded write, retailer decide,
and the ordered three-check verification (state -> SLA -> store count)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_CATEGORY_ADVISOR,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import (
    IMPLEMENTATION_SLA_DAYS,
    SHELF_DECISIONS,
    SHELF_SPACE_CHANGE_MAX_PCT,
    SHELF_TARGET_STORE_COUNT_MAX,
    SHELF_TERMINAL,
)
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical

bp = Blueprint("shelf", __name__)


@bp.post("/jbp/plans/<plan_id>/shelf-recommendations")
def create_shelf_rec(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_CATEGORY_ADVISOR])
    data = V.body()
    V.check_undeclared(
        data,
        {
            "expected_plan_version",
            "title",
            "space_change_pct",
            "target_store_count",
            "sku_adds",
            "sku_drops",
        },
    )
    expected = V.as_int(V.require(data, "expected_plan_version"), "expected_plan_version")
    title = V.as_str(V.require(data, "title"), "title")
    space = V.as_num(V.require(data, "space_change_pct"), "space_change_pct")
    if abs(space) > SHELF_SPACE_CHANGE_MAX_PCT:
        err("ERR_VALIDATION", "|space_change_pct| must be <= 30")
    target = V.as_int(V.require(data, "target_store_count"), "target_store_count")
    if target < 1 or target > SHELF_TARGET_STORE_COUNT_MAX:
        err("ERR_VALIDATION", "target_store_count must be in [1, 10000]")
    sku_adds = V.as_str_list(data.get("sku_adds", []), "sku_adds")
    sku_drops = V.as_str_list(data.get("sku_drops", []), "sku_drops")
    if set(sku_adds) & set(sku_drops):
        err("ERR_VALIDATION", "sku_adds and sku_drops must not intersect")
    plan = plan_or_404(plan_id)  # 6
    # priority 11: the API's single optimistic-concurrency check
    if expected != plan["version"]:
        err("ERR_STALE_VERSION", "expected_plan_version does not match the plan's current version")
    # priority 12: plan must be ACCEPTED or ACTIVATED
    if plan["status"] not in ("ACCEPTED", "ACTIVATED"):
        err("ERR_PLAN_NOT_ACTIVATED", "shelf-recommendation create requires plan ACCEPTED or ACTIVATED")
    # priority 13: at least one ACCEPTED analysis
    has_accepted = any(
        a["plan_id"] == plan_id and a["status"] == "ACCEPTED"
        for a in STORE["analyses"].values()
    )
    if not has_accepted:
        err("ERR_ANALYSIS_NOT_ACCEPTED", "plan has no ACCEPTED category analysis")
    # A successful create supersedes the plan's currently PROPOSED incumbent.
    for rec in STORE["shelf_recs"].values():
        if rec["plan_id"] == plan_id and rec["status"] == "PROPOSED":
            rec["status"] = "WITHDRAWN"
            touch(rec)
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "title": title,
        "space_change_pct": space,
        "target_store_count": target,
        "sku_adds": sku_adds,
        "sku_drops": sku_drops,
        "status": "PROPOSED",
        "accepted_at": None,
        "verified_store_count": None,
        "_accepted_logical": None,
    }
    stamp_new(rec)
    STORE["shelf_recs"][rec["id"]] = rec
    touch(plan)  # the plan's version itself increments by 1
    return success(public(rec), 201)


@bp.get("/jbp/plans/<plan_id>/shelf-recommendations")
def list_shelf_recs(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [r for r in by_seq(STORE["shelf_recs"].values()) if r["plan_id"] == plan_id]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [r for r in items if r["status"] == f_status]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/jbp/shelf-recommendations/<rec_id>/decide")
def decide_shelf_rec(rec_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    rec = STORE["shelf_recs"].get(rec_id)
    plan = STORE["plans"].get(rec["plan_id"]) if rec is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"decision"})
    decision = V.as_enum(V.require(data, "decision"), "decision", SHELF_DECISIONS)  # 4
    if rec is None:
        err("ERR_RESOURCE_NOT_FOUND", "shelf recommendation not found")  # 6
    if rec["status"] in SHELF_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "shelf recommendation is terminal")  # 8
    if rec["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", "only a PROPOSED recommendation can be decided")  # 7
    if decision == "ACCEPT":
        rec["status"] = "IMPLEMENTING"
        rec["accepted_at"] = fmt_logical(clock.now())
        rec["_accepted_logical"] = clock.now()
    else:
        rec["status"] = "REJECTED"
    touch(rec)
    return success(public(rec))


@bp.post("/jbp/shelf-recommendations/<rec_id>/verify")
def verify_shelf_rec(rec_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_CATEGORY_ADVISOR])
    data = V.body()
    V.check_undeclared(data, {"implemented_store_count"})
    count = V.as_int(V.require(data, "implemented_store_count"), "implemented_store_count")
    if count < 0:
        err("ERR_VALIDATION", "implemented_store_count must be >= 0")
    rec = STORE["shelf_recs"].get(rec_id)
    if rec is None:
        err("ERR_RESOURCE_NOT_FOUND", "shelf recommendation not found")  # 6
    # ordered checks (priority 17): (1) state, (2) SLA window, (3) store count
    if rec["status"] in SHELF_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "shelf recommendation is terminal")  # 8
    if rec["status"] != "IMPLEMENTING":
        err("ERR_INVALID_STATE", "only an IMPLEMENTING recommendation can be verified")  # 7
    if clock.now() - rec["_accepted_logical"] > timedelta(days=IMPLEMENTATION_SLA_DAYS):
        # the rejection and the STALLED transition are inseparable
        rec["status"] = "STALLED"
        touch(rec)
        err("ERR_IMPLEMENTATION_STALLED", "implementation SLA of 90 days has lapsed; recommendation stalled")
    if count < rec["target_store_count"]:
        err("ERR_IMPLEMENTATION_INCOMPLETE", "implemented_store_count below target_store_count")
    rec["status"] = "VERIFIED"
    rec["verified_store_count"] = count
    touch(rec)
    return success(public(rec))
