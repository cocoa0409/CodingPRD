"""Zone executions, signage compliance and price application (PRD 3.6)."""

from flask import Blueprint

from common import add_days, days_between, fmt_date, parse_date
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_MERCHANDISE_DIRECTOR, ROLE_PRICING_ANALYST,
                        ROLE_STORE_MANAGER, body, endpoint)
from response import created, ok
from serializers import execution_json
from services import calc, lookup
from services.lifecycle import (claims_of_plan, executions_of_item,
                                executions_of_step, maybe_complete_plan,
                                recompute_plan, refresh_item)

bp = Blueprint("executions", __name__)

SCOPES = ("CHAIN", "ZONE", "STORE")
LIVE_EXECUTION_STATUSES = ("SCHEDULED", "APPLIED")


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@endpoint(bp, "/zone-executions", ["POST"], (ROLE_PRICING_ANALYST,))
def create_execution(user_id, role):
    from validation import opt_str, req_date, req_enum, req_int, req_str
    payload = body()
    plan_id = req_str(payload, "markdown_plan_id")
    step_id = req_str(payload, "markdown_step_id")
    zone_id = req_str(payload, "price_zone_id")
    scope = req_enum(payload, "execution_scope", SCOPES)
    effective_date = req_date(payload, "effective_date")
    units_in_scope = req_int(payload, "units_in_scope", minimum=1)
    store_id = opt_str(payload, "store_id")

    plan = lookup.plan(plan_id)
    step = lookup.step(step_id)
    zone = lookup.price_zone(zone_id)
    store = lookup.store(store_id) if store_id is not None else None

    season = lookup.season(plan["season_id"])
    item = lookup.item(plan["item_id"])
    lookup.gate_active(season)

    if plan["status"] not in ("APPROVED", "EXECUTING"):
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "The plan must be APPROVED or EXECUTING to schedule "
                       "an execution.")

    lead_days = zone["signage_lead_days"]

    # 20: signage lead time
    if add_days(effective_date, -lead_days) < db.clock_date():
        raise ApiError("ERR_SIGNAGE_LEAD_VIOLATION",
                       "The zone needs %d days of signage lead time."
                       % lead_days)

    live = [e for e in executions_of_item(item)
            if e["status"] in LIVE_EXECUTION_STATUSES]

    # 23: store-scope occupancy over the rung's half-open window
    if scope == "STORE" and store is not None:
        new_start = parse_date(step["effective_date"])
        new_end = parse_date(step["window_end_date_exclusive"])
        for other in live:
            if other["store_id"] != store["id"]:
                continue
            other_step = db.get("steps", other["markdown_step_id"])
            if other_step is None:
                continue
            other_start = parse_date(other_step["effective_date"])
            other_end = parse_date(other_step["window_end_date_exclusive"])
            if _overlaps(new_start, new_end, other_start, other_end):
                raise ApiError("ERR_STEP_WINDOW_OVERLAP",
                               "The rung window already occupies this store.")

    # 24: minimum spacing between executions on one item inside a zone
    for other in live:
        if other["price_zone_id"] != zone["id"]:
            continue
        gap = abs(days_between(parse_date(other["effective_date"]),
                               effective_date))
        if gap < lead_days:
            raise ApiError("ERR_ZONE_SIGNAGE_WINDOW_CONFLICT",
                           "Two executions on this item inside the zone must "
                           "be at least %d days apart." % lead_days)

    # 25: scope integrity
    if scope == "CHAIN":
        if zone["zone_type"] != "CHAIN" or store is not None:
            raise ApiError("ERR_ZONE_SCOPE_MISMATCH",
                           "A CHAIN execution needs a CHAIN zone and no store.")
    elif scope == "ZONE":
        if zone["zone_type"] != "REGION" or store is not None:
            raise ApiError("ERR_ZONE_SCOPE_MISMATCH",
                           "A ZONE execution needs a REGION zone and no store.")
    else:
        if zone["zone_type"] not in ("STORE", "REGION") or store is None or \
                store["price_zone_id"] != zone["id"]:
            raise ApiError("ERR_ZONE_SCOPE_MISMATCH",
                           "A STORE execution needs a STORE or REGION zone and "
                           "a store inside it.")
    if fmt_date(effective_date) != step["effective_date"]:
        raise ApiError("ERR_ZONE_SCOPE_MISMATCH",
                       "The execution's effective_date must equal the rung's.")
    if step["markdown_plan_id"] != plan["id"]:
        raise ApiError("ERR_ZONE_SCOPE_MISMATCH",
                       "The rung does not belong to the plan.")

    # 28: units in scope against the on-hand pool
    committed_units = sum(e["units_in_scope"] for e in live)
    if units_in_scope + committed_units > item["on_hand_units"]:
        raise ApiError("ERR_ZONE_UNITS_EXCEED_ON_HAND",
                       "Scheduled units would exceed the item's on-hand units.")

    execution = new_row(
        markdown_plan_id=plan["id"],
        markdown_step_id=step["id"],
        price_zone_id=zone["id"],
        store_id=store["id"] if store is not None else None,
        execution_scope=scope,
        effective_date=fmt_date(effective_date),
        units_in_scope=units_in_scope,
        signage_due_date=fmt_date(add_days(effective_date, -lead_days)),
        signage_status="PENDING",
        posted_at=None,
        posted_by_user_id=None,
        verified_by_user_id=None,
        per_unit_markdown_cents=0,
        line_markdown_cents=0,
        # PRD 3.6: the new execution "leaves per_unit_markdown_cents,
        # line_markdown_cents and price_cents_applied at 0 and applied_at,
        # posted_at, posted_by_user_id and verified_by_user_id null".
        price_cents_applied=0,
        applied_at=None,
        status="SCHEDULED",
    )
    db.insert("executions", execution)

    if step["status"] == "PLANNED":
        step["status"] = "SCHEDULED"
        touch(step)
    recompute_plan(plan, force=True)
    return created(execution_json(execution))


@endpoint(bp, "/zone-executions/<zone_execution_id>/post-signage", ["POST"],
          (ROLE_STORE_MANAGER,))
def post_signage(user_id, role, zone_execution_id):
    execution = lookup.execution(zone_execution_id)

    # 6: a STORE-scope execution belongs to the acting store manager
    if execution["execution_scope"] == "STORE" and \
            execution["store_id"] != user_id:
        raise ApiError("ERR_STORE_NOT_OWNED",
                       "The execution belongs to another store.")

    if execution["signage_status"] != "PENDING":
        raise ApiError("ERR_SIGNAGE_ALREADY_POSTED",
                       "Signage has already left the PENDING state.")

    plan = lookup.plan(execution["markdown_plan_id"])
    lookup.gate_not_closed(lookup.season(plan["season_id"]))

    on_time = db.clock_date() <= parse_date(execution["signage_due_date"])
    execution["signage_status"] = "POSTED" if on_time else "NON_COMPLIANT"
    execution["posted_at"] = db.clock_instant()
    execution["posted_by_user_id"] = user_id
    touch(execution)
    return ok(execution_json(execution))


@endpoint(bp, "/zone-executions/<zone_execution_id>/verify-signage", ["POST"],
          (ROLE_MERCHANDISE_DIRECTOR,))
def verify_signage(user_id, role, zone_execution_id):
    execution = lookup.execution(zone_execution_id)
    if execution["signage_status"] != "POSTED":
        raise ApiError("ERR_SIGNAGE_NOT_POSTED",
                       "Only POSTED signage may be verified.")
    plan = lookup.plan(execution["markdown_plan_id"])
    lookup.gate_not_closed(lookup.season(plan["season_id"]))

    execution["signage_status"] = "VERIFIED"
    execution["verified_by_user_id"] = user_id
    touch(execution)
    return ok(execution_json(execution))


@endpoint(bp, "/zone-executions/<zone_execution_id>/apply", ["POST"],
          (ROLE_PRICING_ANALYST,))
def apply_execution(user_id, role, zone_execution_id):
    execution = lookup.execution(zone_execution_id)
    plan = lookup.plan(execution["markdown_plan_id"])
    step = lookup.step(execution["markdown_step_id"])
    item = lookup.item(plan["item_id"])
    season = lookup.season(plan["season_id"])

    if execution["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED execution may be applied.")
    lookup.gate_not_closed(season)
    if item["markdown_state"] not in ("FULL_PRICE", "PROMO_ACTIVE",
                                     "PERM_MARKED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The item's markdown_state cannot absorb another "
                       "markdown.")
    if db.clock_date() < parse_date(execution["effective_date"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The execution's effective_date has not arrived.")
    if execution["units_in_scope"] > item["on_hand_units"]:
        raise ApiError("ERR_INVALID_STATE",
                       "units_in_scope exceeds the item's on-hand units.")
    if step["price_cents"] >= item["current_retail_cents"]:
        raise ApiError("ERR_INVALID_STATE",
                       "The rung price is not strictly below the item's "
                       "current retail.")

    if plan["status"] not in ("APPROVED", "EXECUTING"):
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "The plan must be APPROVED or EXECUTING to apply.")
    if execution["signage_status"] != "VERIFIED":
        raise ApiError("ERR_SIGNAGE_NOT_VERIFIED",
                       "Signage must be VERIFIED before the price moves.")

    per_unit = item["current_retail_cents"] - step["price_cents"]
    execution["per_unit_markdown_cents"] = per_unit
    execution["line_markdown_cents"] = per_unit * execution["units_in_scope"]
    execution["price_cents_applied"] = step["price_cents"]
    execution["applied_at"] = db.clock_instant()
    execution["status"] = "APPLIED"
    touch(execution)

    # hop 1: the ticket and the rung
    item["current_retail_cents"] = step["price_cents"]
    if step["status"] != "EXECUTED":
        step["status"] = "EXECUTED"
        touch(step)

    # hop 2: the item's markdown dimension
    depth = _depth(step["depth_pct"])
    state = item["markdown_state"]
    if plan["plan_type"] == "PROMOTIONAL" and depth < calc.EXIT_DEPTH_PCT:
        if state == "FULL_PRICE":
            item["markdown_state"] = "PROMO_ACTIVE"
    elif plan["plan_type"] == "PERMANENT" and depth < calc.EXIT_DEPTH_PCT:
        if state in ("FULL_PRICE", "PROMO_ACTIVE"):
            item["markdown_state"] = "PERM_MARKED"
    elif plan["plan_type"] == "PERMANENT" and depth >= calc.EXIT_DEPTH_PCT:
        if state == "PERM_MARKED":
            item["markdown_state"] = "EXIT_PRICED"

    # hops 3, 4 and 5: lifecycle, reservations and the season
    refresh_item(item, force=True)

    if plan["status"] == "APPROVED":
        plan["status"] = "EXECUTING"
    recompute_plan(plan, force=True)
    maybe_complete_plan(plan)
    return ok(execution_json(execution))


def _depth(value):
    from common import dec
    return dec(value)


@endpoint(bp, "/zone-executions/<zone_execution_id>/roll-back", ["POST"],
          (ROLE_PRICING_ANALYST,))
def roll_back_execution(user_id, role, zone_execution_id):
    from validation import req_str
    payload = body()
    req_str(payload, "rollback_reason", min_len=1, max_len=1024)
    execution = lookup.execution(zone_execution_id)
    plan = lookup.plan(execution["markdown_plan_id"])
    step = lookup.step(execution["markdown_step_id"])
    item = lookup.item(plan["item_id"])
    season = lookup.season(plan["season_id"])

    if execution["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an APPLIED execution may be rolled back.")
    for claim in claims_of_plan(plan):
        if claim["status"] == "RECOGNIZED":
            raise ApiError("ERR_INVALID_STATE",
                           "A RECOGNIZED vendor claim still references this "
                           "plan.")
    lookup.gate_not_closed(season)

    execution["status"] = "ROLLED_BACK"
    touch(execution)

    remaining = [e for e in executions_of_item(item)
                 if e["status"] == "APPLIED"]
    if not remaining:
        item["current_retail_cents"] = item["original_retail_cents"]
        if item["markdown_state"] in ("PROMO_ACTIVE", "PERM_MARKED"):
            item["markdown_state"] = "FULL_PRICE"
    else:
        latest = sorted(remaining,
                        key=lambda e: (e["effective_date"], e["created_at"]))[-1]
        item["current_retail_cents"] = latest["price_cents_applied"]

    sibling_applied = [e for e in executions_of_step(step)
                       if e["status"] == "APPLIED"]
    if not sibling_applied and step["status"] == "EXECUTED":
        step["status"] = "SCHEDULED"
        touch(step)

    refresh_item(item, force=True)
    recompute_plan(plan, force=True)
    return ok(execution_json(execution))
