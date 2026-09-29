"""Markdown plans, their depth ladders and the revision cycle (PRD 3.5)."""

from flask import Blueprint

from common import days_between, fmt_date, parse_date, r2
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_MERCHANDISE_DIRECTOR, ROLE_PRICING_ANALYST, body,
                        endpoint)
from response import created, ok
from serializers import plan_json, step_json
from services import calc, lookup
from services.lifecycle import (PLAN_SUPERSEDABLE, executions_of_plan,
                                is_markdown_eligible, live_steps_of_plan,
                                plans_of_item, recompute_plan,
                                recompute_season, recompute_store,
                                refresh_item, reservations_of_plan,
                                steps_of_plan, weeks_to_exit)

bp = Blueprint("plans", __name__)

PLAN_TYPES = ("PERMANENT", "PROMOTIONAL")


@endpoint(bp, "/markdown-plans", ["POST"], (ROLE_PRICING_ANALYST,))
def create_plan(user_id, role):
    from validation import req_date, req_enum, req_int, req_str
    payload = body()
    season_id = req_str(payload, "season_id")
    item_id = req_str(payload, "item_id")
    estimate_id = req_str(payload, "elasticity_estimate_id")
    plan_type = req_enum(payload, "plan_type", PLAN_TYPES)
    exit_date_target = req_date(payload, "exit_date_target")
    expected_item_version = req_int(payload, "expected_item_version", minimum=1)

    season = lookup.season(season_id)
    item = lookup.item(item_id)
    estimate = lookup.estimate(estimate_id)

    if exit_date_target > parse_date(season["exit_target_date"]):
        raise ApiError("ERR_VALIDATION",
                       "exit_date_target may not fall after the season's "
                       "exit_target_date.")

    if expected_item_version != item["version"]:
        raise ApiError("ERR_STALE_ITEM_VERSION",
                       "expected_item_version does not match the item.")

    lookup.gate_active(season)

    priors = [p for p in plans_of_item(item)
              if p["season_id"] == season["id"] and p["status"] != "SUPERSEDED"]
    for prior in priors:
        for execution in executions_of_plan(prior):
            if execution["status"] == "APPLIED":
                raise ApiError("ERR_PLAN_ALREADY_EXECUTING",
                               "An earlier plan for this item already has an "
                               "applied execution.")

    plan = new_row(
        season_id=season["id"],
        item_id=item["id"],
        elasticity_estimate_id=estimate["id"],
        plan_type=plan_type,
        exit_date_target=fmt_date(exit_date_target),
        created_by_user_id=user_id,
        approved_by_user_id=None,
        revision_round=0,
        recommended_depth_pct=calc.recommended_depth_pct(
            item["lifecycle_stage"], weeks_to_exit(season),
            item["weeks_of_supply"], estimate["elasticity_coefficient"]),
        ladder_step_count=0,
        gross_markdown_cents=0,
        vendor_funded_cents=0,
        net_markdown_cents=0,
        projected_exit_units=0,
        superseded_by_plan_id=None,
        status="DRAFT",
    )
    db.insert("plans", plan)

    stores = {}
    for prior in priors:
        if prior["status"] not in PLAN_SUPERSEDABLE:
            continue
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_plan_id"] = plan["id"]
        touch(prior)
        for step in steps_of_plan(prior):
            if step["status"] in ("PLANNED", "SCHEDULED"):
                step["status"] = "SUPERSEDED"
                touch(step)
        for reservation in reservations_of_plan(prior):
            if reservation["status"] in ("RESERVED", "COMMITTED"):
                reservation["status"] = "RELEASED"
                reservation["released_at"] = db.clock_instant()
                touch(reservation)
                stores[reservation["store_id"]] = True
        recompute_plan(prior)

    for store_id in stores:
        store = db.get("stores", store_id)
        if store is not None:
            recompute_store(store)
    recompute_season(season)
    refresh_item(item, force=True)
    return created(plan_json(plan))


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/steps", ["POST"],
          (ROLE_PRICING_ANALYST,))
def create_step(user_id, role, markdown_plan_id):
    from validation import req_date, req_int, req_num
    payload = body()
    step_index = req_int(payload, "step_index", minimum=1)
    effective_date = req_date(payload, "effective_date")
    depth_pct = req_num(payload, "depth_pct", minimum="0.01", maximum="70.00")

    plan = lookup.plan(markdown_plan_id)
    season = lookup.season(plan["season_id"])
    item = lookup.item(plan["item_id"])
    lookup.gate_not_closed(season)

    live = live_steps_of_plan(plan)
    previous = live[-1] if live else None

    # 17: protected period, equality is still a violation
    if effective_date <= parse_date(item["protected_until_date"]):
        raise ApiError("ERR_PROTECTED_PERIOD_ACTIVE",
                       "The rung falls inside the item's protected period.")

    # 18: cadence between consecutive rungs
    if previous is not None:
        gap = days_between(parse_date(previous["effective_date"]),
                           effective_date)
        if gap < calc.MIN_CADENCE_DAYS:
            raise ApiError("ERR_CADENCE_TOO_TIGHT",
                           "Consecutive rungs must be at least %d days apart."
                           % calc.MIN_CADENCE_DAYS)

    # 19: exit framing
    exit_target = parse_date(plan["exit_date_target"])
    if days_between(effective_date, exit_target) < calc.EXIT_BUFFER_DAYS:
        raise ApiError("ERR_EXIT_DATE_MISSED",
                       "The rung leaves less than the %d-day exit buffer."
                       % calc.EXIT_BUFFER_DAYS)
    if effective_date < db.clock_date():
        raise ApiError("ERR_EFFECTIVE_DATE_IN_PAST",
                       "effective_date is already in the past.")

    # 22: ladder shape
    if step_index != plan["ladder_step_count"] + 1:
        raise ApiError("ERR_STEP_INDEX_OUT_OF_SEQUENCE",
                       "step_index must be exactly one greater than the "
                       "plan's ladder_step_count.")
    if plan["ladder_step_count"] >= calc.MAX_LADDER_STEPS:
        raise ApiError("ERR_MAX_LADDER_STEPS",
                       "A ladder carries at most %d rungs."
                       % calc.MAX_LADDER_STEPS)
    if previous is not None and depth_pct <= _dec(previous["depth_pct"]):
        raise ApiError("ERR_DEPTH_NOT_MONOTONIC",
                       "depth_pct must be strictly greater than the previous "
                       "rung's depth_pct.")

    step = new_row(
        markdown_plan_id=plan["id"],
        step_index=step_index,
        effective_date=fmt_date(effective_date),
        depth_pct=r2(depth_pct),
        price_cents=calc.rung_price_cents(item["original_retail_cents"],
                                         depth_pct),
        window_end_date_exclusive=plan["exit_date_target"],
        status="PLANNED",
    )
    db.insert("steps", step)

    if previous is not None:
        previous["window_end_date_exclusive"] = fmt_date(effective_date)
        touch(previous)

    recompute_plan(plan, force=True)
    return created(step_json(step))


def _dec(value):
    from common import dec
    return dec(value)


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/submit", ["POST"],
          (ROLE_PRICING_ANALYST,))
def submit_plan(user_id, role, markdown_plan_id):
    plan = lookup.plan(markdown_plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT plan may be submitted.")
    season = lookup.season(plan["season_id"])
    lookup.gate_active(season)

    estimate = db.get("estimates", plan["elasticity_estimate_id"])
    if estimate is None or estimate["status"] != "CERTIFIED" or \
            estimate["item_id"] != plan["item_id"]:
        raise ApiError("ERR_ELASTICITY_NOT_CERTIFIED",
                       "The plan needs a CERTIFIED estimate for its own item.")

    item = lookup.item(plan["item_id"])
    if not is_markdown_eligible(item):
        raise ApiError("ERR_MARKDOWN_NOT_ELIGIBLE",
                       "The item's lifecycle_stage is not markdown eligible.")

    if plan["ladder_step_count"] < 1:
        raise ApiError("ERR_EMPTY_LADDER", "The plan carries no ladder rung.")

    plan["status"] = "SUBMITTED"
    recompute_plan(plan, force=True)
    return ok(plan_json(plan))


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/request-revision", ["POST"],
          (ROLE_MERCHANDISE_DIRECTOR,))
def request_revision(user_id, role, markdown_plan_id):
    from validation import req_str
    payload = body()
    req_str(payload, "revision_reason", min_len=1, max_len=1024)
    plan = lookup.plan(markdown_plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED plan may be sent back for revision.")
    lookup.gate_not_closed(lookup.season(plan["season_id"]))

    plan["status"] = "REVISION_REQUESTED"
    plan["revision_round"] = plan["revision_round"] + 1
    recompute_plan(plan, force=True)
    return ok(plan_json(plan))


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/reopen", ["POST"],
          (ROLE_PRICING_ANALYST,))
def reopen_plan(user_id, role, markdown_plan_id):
    from validation import opt_bool
    payload = body()
    clear_ladder = opt_bool(payload, "clear_ladder", default=False)
    plan = lookup.plan(markdown_plan_id)
    if plan["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REVISION_REQUESTED plan may be reopened.")
    lookup.gate_not_closed(lookup.season(plan["season_id"]))
    if plan["revision_round"] > calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_ROUNDS_EXHAUSTED",
                       "The plan has exhausted its revision rounds.")

    plan["status"] = "DRAFT"
    if clear_ladder:
        for step in steps_of_plan(plan):
            if step["status"] == "PLANNED":
                step["status"] = "SUPERSEDED"
                touch(step)
    recompute_plan(plan, force=True)
    return ok(plan_json(plan))


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/approve", ["POST"],
          (ROLE_MERCHANDISE_DIRECTOR,))
def approve_plan(user_id, role, markdown_plan_id):
    plan = lookup.plan(markdown_plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED plan may be approved.")
    season = lookup.season(plan["season_id"])
    lookup.gate_active(season)
    if user_id == plan["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver may not be the plan's author.")

    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    recompute_plan(plan, force=True)
    return ok(plan_json(plan))
