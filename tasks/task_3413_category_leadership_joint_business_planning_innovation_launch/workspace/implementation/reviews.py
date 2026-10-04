"""PerformanceReview: opening (which computes attainment, bias, friction,
risk score and posture), listing, and retailer finalization with the
CONTINUE/DELIST propagation and the pack-family retirement cascade."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import (
    LAUNCH_TERMINAL,
    REVIEW_DECISIONS,
    REVIEW_MIN_DAYS_AFTER_LAUNCH,
    REVIEW_TERMINAL,
)
from envelope import success, success_list
from errors import err
from launches import get_launch
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical

bp = Blueprint("reviews", __name__)


@bp.post("/jbp/launches/<launch_id>/performance-reviews")
def create_review(launch_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(
        data,
        {
            "period_start",
            "period_end",
            "actual_sales_cents",
            "sales_target_cents",
            "target_distribution_pct",
            "distribution_achieved_pct",
        },
    )
    period_start = V.as_dt(V.require(data, "period_start"), "period_start")
    period_end = V.as_dt(V.require(data, "period_end"), "period_end")
    if period_end <= period_start:
        err("ERR_VALIDATION", "period_end must be strictly after period_start")
    actual = V.as_int(V.require(data, "actual_sales_cents"), "actual_sales_cents")
    if actual < 0:
        err("ERR_VALIDATION", "actual_sales_cents must be >= 0")
    target_sales = V.as_int(V.require(data, "sales_target_cents"), "sales_target_cents")
    if target_sales <= 0:
        err("ERR_VALIDATION", "sales_target_cents must be > 0")
    target_dist = V.as_num(V.require(data, "target_distribution_pct"), "target_distribution_pct")
    if target_dist < 0 or target_dist > 100:
        err("ERR_VALIDATION", "target_distribution_pct must be in [0, 100]")
    achieved_dist = V.as_num(
        V.require(data, "distribution_achieved_pct"), "distribution_achieved_pct"
    )
    if achieved_dist < 0 or achieved_dist > 100:
        err("ERR_VALIDATION", "distribution_achieved_pct must be in [0, 100]")
    launch = get_launch(launch_id)
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")  # 6
    if launch["status"] in LAUNCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "launch is terminal")  # 8
    if launch["status"] != "LAUNCHED":
        err("ERR_INVALID_STATE", "review opens on a launched product")  # 7
    # priority 20: at most one review per launch
    for r in STORE["reviews"].values():
        if r["launch_id"] == launch_id:
            err("ERR_REVIEW_ALREADY_EXISTS", "a review already exists for this launch")
    # priority 32: clock >= launch_date + 84 days (boundary passes)
    if clock.now() < launch["_launch_date_dt"] + timedelta(days=REVIEW_MIN_DAYS_AFTER_LAUNCH):
        err("ERR_REVIEW_TOO_EARLY", "review window opens 84 days after launch_date")
    # creation is computation
    attainment = calc.rhu_2dp(calc.D(actual) * 100 / calc.D(target_sales))
    bias = calc.forecast_bias_pct(launch["plan_id"], period_start, period_end)
    fund = calc.fund_of_plan(launch["plan_id"])
    friction = calc.friction_count(fund["id"], period_start, period_end) if fund else 0
    score, posture = calc.risk_score_posture(attainment, target_dist, achieved_dist, bias, friction)
    rec = {
        "id": new_id(),
        "launch_id": launch_id,
        "period_start": fmt_logical(period_start),
        "period_end": fmt_logical(period_end),
        "actual_sales_cents": actual,
        "sales_target_cents": target_sales,
        "target_distribution_pct": target_dist,
        "distribution_achieved_pct": achieved_dist,
        "sales_attainment_pct": calc.num_out(attainment),
        "forecast_bias_pct": calc.num_out(bias),
        "friction_count": friction,
        "risk_score": score,
        "risk_posture": posture,
        "status": "OPEN",
        "decision": None,
        "_period_start_dt": period_start,
        "_period_end_dt": period_end,
    }
    stamp_new(rec)
    STORE["reviews"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.get("/jbp/launches/<launch_id>/performance-reviews")
def list_reviews(launch_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    launch = get_launch(launch_id)
    if launch is not None:
        scope_plan(uid, role, STORE["plans"].get(launch["plan_id"]))
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")
    items = [r for r in by_seq(STORE["reviews"].values()) if r["launch_id"] == launch_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/jbp/performance-reviews/<review_id>/finalize")
def finalize_review(review_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    review = STORE["reviews"].get(review_id)
    launch = STORE["launches"].get(review["launch_id"]) if review is not None else None
    plan = STORE["plans"].get(launch["plan_id"]) if launch is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"decision"})
    decision = V.as_enum(V.require(data, "decision"), "decision", REVIEW_DECISIONS)  # 4
    if review is None:
        err("ERR_RESOURCE_NOT_FOUND", "performance review not found")  # 6
    if review["status"] in REVIEW_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "review is FINALIZED")  # 8
    review["decision"] = decision
    review["status"] = "FINALIZED"
    touch(review)
    # decision propagation onto the launch
    if decision == "CONTINUE":
        launch["status"] = "REVIEWED"
        touch(launch)
    else:
        launch["status"] = "DELISTED"
        touch(launch)
        # pack-family cascade: every APPROVED price-pack decision of the same
        # plan sharing the launch's pack_family is retired by the system
        for ppd in STORE["ppds"].values():
            if (
                ppd["plan_id"] == launch["plan_id"]
                and ppd["pack_family"] == launch["pack_family"]
                and ppd["status"] == "APPROVED"
            ):
                ppd["status"] = "RETIRED"
                touch(ppd)
    return success(public(review))
