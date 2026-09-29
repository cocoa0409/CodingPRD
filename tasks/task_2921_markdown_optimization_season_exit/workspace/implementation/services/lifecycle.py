"""Relationship helpers, item lifecycle classification and counter cascades."""

from decimal import Decimal

from common import days_between, dec, parse_date, whole_weeks
from db import apply_changes, db, touch
from services import calc

# PRD 3.3 qualifies only the RESERVED -> COMMITTED direction with "the item's
# non-terminal plans"; the reverse is "it reverts that plan's COMMITTED
# reservations back to RESERVED" (PRD 3.3, restated in 3.6) with no such
# qualifier. COMPLETED is never declared terminal for a plan -- PRD 3.4 still
# counts it in projected_exit_units and PRD 3.5 says "Both EXECUTING and
# COMPLETED are claimable" -- so only SUPERSEDED is excluded here, whose
# reservations PRD 3.5 has already moved to RELEASED anyway.
PLAN_TERMINAL = ("SUPERSEDED",)
PLAN_SUPERSEDABLE = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED")
MARKDOWN_ELIGIBLE_STAGES = ("AGING", "CLEARANCE", "EXIT_PENDING")
DISPOSITION_ELIGIBLE_STAGES = ("CLEARANCE", "EXIT_PENDING")


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------

def _by_created(rows):
    return sorted(rows, key=lambda r: r["created_at"])


def items_of_season(season):
    return _by_created([r for r in db.items.values()
                        if r["season_id"] == season["id"]])


def plans_of_season(season):
    return _by_created([r for r in db.plans.values()
                        if r["season_id"] == season["id"]])


def plans_of_item(item):
    return _by_created([r for r in db.plans.values()
                        if r["item_id"] == item["id"]])


def sales_weeks_of_item(item):
    rows = [r for r in db.sales_weeks.values() if r["item_id"] == item["id"]]
    return sorted(rows, key=lambda r: (r["week_ending_date"], r["created_at"]))


def estimates_of_item(item):
    return _by_created([r for r in db.estimates.values()
                        if r["item_id"] == item["id"]])


def steps_of_plan(plan):
    rows = [r for r in db.steps.values()
            if r["markdown_plan_id"] == plan["id"]]
    return sorted(rows, key=lambda r: (r["step_index"], r["created_at"]))


def live_steps_of_plan(plan):
    return [s for s in steps_of_plan(plan) if s["status"] != "SUPERSEDED"]


def executions_of_plan(plan):
    return _by_created([r for r in db.executions.values()
                        if r["markdown_plan_id"] == plan["id"]])


def executions_of_step(step):
    return _by_created([r for r in db.executions.values()
                        if r["markdown_step_id"] == step["id"]])


def executions_of_item(item):
    plan_ids = set(p["id"] for p in plans_of_item(item))
    return _by_created([r for r in db.executions.values()
                        if r["markdown_plan_id"] in plan_ids])


def reservations_of_plan(plan):
    return _by_created([r for r in db.reservations.values()
                        if r["markdown_plan_id"] == plan["id"]])


def reservations_of_season(season):
    return _by_created([r for r in db.reservations.values()
                        if r["season_id"] == season["id"]])


def reservations_of_store(store):
    return _by_created([r for r in db.reservations.values()
                        if r["store_id"] == store["id"]])


def reservations_of_item(item):
    plan_ids = set(p["id"] for p in plans_of_item(item)
                   if p["status"] not in PLAN_TERMINAL)
    return _by_created([r for r in db.reservations.values()
                        if r["markdown_plan_id"] in plan_ids])


def claims_of_plan(plan):
    return _by_created([r for r in db.claims.values()
                        if r["markdown_plan_id"] == plan["id"]])


def claims_of_agreement(agreement):
    return _by_created([r for r in db.claims.values()
                        if r["allowance_agreement_id"] == agreement["id"]])


def agreements_of_season(season):
    return _by_created([r for r in db.agreements.values()
                        if r["season_id"] == season["id"]])


def dispositions_of_item(item):
    return _by_created([r for r in db.dispositions.values()
                        if r["item_id"] == item["id"]])


def dispositions_of_season(season):
    return _by_created([r for r in db.dispositions.values()
                        if r["season_id"] == season["id"]])


def exit_reviews_of_season(season):
    return _by_created([r for r in db.exit_reviews.values()
                        if r["season_id"] == season["id"]])


def season_of_item(item):
    return db.get("seasons", item["season_id"])


def season_of_plan(plan):
    return db.get("seasons", plan["season_id"])


def item_of_plan(plan):
    return db.get("items", plan["item_id"])


# --------------------------------------------------------------------------
# Temporal helpers (PRD 3.3)
# --------------------------------------------------------------------------

def weeks_on_hand(item):
    first = parse_date(item["first_receipt_date"])
    return whole_weeks(days_between(first, db.clock_date()))


def weeks_to_exit(season):
    target = parse_date(season["exit_target_date"])
    return whole_weeks(days_between(db.clock_date(), target))


# --------------------------------------------------------------------------
# Classification (PRD 3.3): six rules, top down, first match wins
# --------------------------------------------------------------------------

def classify(view):
    season = db.get("seasons", view["season_id"])
    current = db.clock_date()
    protected = parse_date(view["protected_until_date"])
    on_hand = whole_weeks(days_between(parse_date(view["first_receipt_date"]),
                                       current))
    to_exit = whole_weeks(days_between(
        current, parse_date(season["exit_target_date"]))) if season else 0
    slow_seller = (dec(view["sell_through_pct"]) <
                   calc.SLOW_SELLER_SELL_THROUGH_PCT and
                   on_hand >= calc.SLOW_SELLER_MIN_WEEKS)

    if view["on_hand_units"] == 0 and view["units_disposed_total"] > 0:
        return "DISPOSED"
    if current <= protected:
        return "NEW_ARRIVAL"
    if season is not None and season["status"] == "EXIT_WINDOW" and \
            to_exit <= calc.EXIT_PENDING_WEEKS_TO_EXIT:
        return "EXIT_PENDING"
    if view["markdown_state"] in ("PERM_MARKED", "EXIT_PRICED") or \
            to_exit <= calc.CLEARANCE_WEEKS_TO_EXIT:
        return "CLEARANCE"
    if on_hand >= calc.AGING_WEEKS_ON_HAND or slow_seller:
        return "AGING"
    return "CORE"


# --------------------------------------------------------------------------
# Derived item aggregates (PRD 3.2, 2.9)
# --------------------------------------------------------------------------

def _units_sold_on_or_after(item, effective_date):
    total = 0
    for week in sales_weeks_of_item(item):
        if week["week_ending_date"] >= effective_date:
            total += week["units_sold"]
    return total


def _item_aggregates(item):
    weeks = sales_weeks_of_item(item)
    units_sold_total = sum(w["units_sold"] for w in weeks)
    sample_weeks = len(weeks)
    orders = dispositions_of_item(item)
    units_disposed_total = sum(o["settled_units"] for o in orders
                               if o["status"] == "SETTLED")
    units_committed = sum(o["units"] for o in orders
                          if o["status"] in ("DRAFT", "APPROVED"))
    on_hand = item["units_received_total"] - units_sold_total - \
        units_disposed_total

    permanent_reserve = 0
    promo_discount = 0
    for execution in executions_of_item(item):
        if execution["status"] != "APPLIED":
            continue
        plan = db.get("plans", execution["markdown_plan_id"])
        if plan is None:
            continue
        if plan["plan_type"] == "PERMANENT":
            permanent_reserve += execution["line_markdown_cents"]
        else:
            sold = _units_sold_on_or_after(item, execution["effective_date"])
            promo_discount += execution["per_unit_markdown_cents"] * sold

    return {
        "units_sold_total": units_sold_total,
        "sample_weeks": sample_weeks,
        "units_disposed_total": units_disposed_total,
        "units_committed_disposition": units_committed,
        "on_hand_units": on_hand,
        "sell_through_pct": calc.sell_through_pct(
            units_sold_total, item["units_received_total"]),
        "weeks_of_supply": calc.weeks_of_supply(
            on_hand, units_sold_total, sample_weeks),
        "permanent_markdown_reserve_cents": permanent_reserve,
        "promo_discount_cents": promo_discount,
    }


# --------------------------------------------------------------------------
# Counter recomputation
# --------------------------------------------------------------------------

def recompute_store(store):
    committed = 0
    for reservation in reservations_of_store(store):
        if reservation["status"] in ("RESERVED", "COMMITTED"):
            committed += reservation["reserved_units"]
    return apply_changes(store, {
        "committed_clearance_units": committed,
        "available_clearance_units": store["clearance_bay_units"] - committed,
    })


def recompute_season(season, cascade=True, force=False):
    reserved = 0
    committed = 0
    for reservation in reservations_of_season(season):
        if reservation["status"] == "RESERVED":
            reserved += reservation["reserved_units"]
        elif reservation["status"] == "COMMITTED":
            committed += reservation["reserved_units"]
    projected = 0
    for plan in plans_of_season(season):
        if plan["status"] in ("APPROVED", "EXECUTING", "COMPLETED"):
            projected += plan["projected_exit_units"]
    changes = {
        "reserved_clearance_units": reserved,
        "committed_clearance_units": committed,
        "projected_exit_units": projected,
    }
    changed = any(season.get(k) != v for k, v in changes.items())
    season.update(changes)
    if changed or force:
        touch(season)
    if cascade:
        maybe_trigger_exit_window(season)
    return changed


def recompute_plan(plan, force=False):
    gross = 0
    projected = 0
    for execution in executions_of_plan(plan):
        if execution["status"] == "APPLIED":
            gross += execution["line_markdown_cents"]
            projected += execution["units_in_scope"]
        elif execution["status"] == "SCHEDULED":
            projected += execution["units_in_scope"]
    funded = sum(c["recognized_cents"] for c in claims_of_plan(plan)
                 if c["status"] == "RECOGNIZED")
    changes = {
        "ladder_step_count": len(live_steps_of_plan(plan)),
        "gross_markdown_cents": gross,
        "vendor_funded_cents": funded,
        "net_markdown_cents": gross - funded,
        "projected_exit_units": projected,
    }
    changed = any(plan.get(k) != v for k, v in changes.items())
    plan.update(changes)
    if changed or force:
        touch(plan)
    season = season_of_plan(plan)
    if season is not None:
        recompute_season(season)
    return changed


def maybe_complete_plan(plan):
    """EXECUTING -> COMPLETED (PRD 3.5)."""
    if plan["status"] != "EXECUTING":
        return False
    item = item_of_plan(plan)
    live = live_steps_of_plan(plan)
    settled = item is not None and item["markdown_state"] == "SETTLED"
    all_executed = bool(live) and all(s["status"] == "EXECUTED" for s in live)
    if settled or all_executed:
        plan["status"] = "COMPLETED"
        touch(plan)
        season = season_of_plan(plan)
        if season is not None:
            recompute_season(season)
        return True
    return False


_triggering = [False]


def maybe_trigger_exit_window(season):
    """Auto ACTIVE -> EXIT_WINDOW on the 60 percent commitment threshold."""
    if _triggering[0]:
        return False
    if season["status"] != "ACTIVE":
        return False
    threshold = calc.exit_window_trigger_units(season["exit_units_target"])
    if season["committed_clearance_units"] < threshold:
        return False
    season["status"] = "EXIT_WINDOW"
    touch(season)
    _triggering[0] = True
    try:
        reclassify_season_items(season)
    finally:
        _triggering[0] = False
    return True


# --------------------------------------------------------------------------
# Item refresh and lifecycle side effects
# --------------------------------------------------------------------------

_sweeping = [False]


def refresh_item(item, force=False, silent=False):
    """Recompute the item's derived fields and re-run classification.

    The whole refresh costs the item at most one version increment, so a
    request that mutates an item bumps its version exactly once (PRD 2.4).
    """
    previous_stage = item["lifecycle_stage"]
    changes = _item_aggregates(item)
    view = dict(item)
    view.update(changes)

    if view["on_hand_units"] == 0 and \
            view["markdown_state"] in ("PERM_MARKED", "EXIT_PRICED"):
        changes["markdown_state"] = "SETTLED"
        view["markdown_state"] = "SETTLED"

    stage = classify(view)
    changes["lifecycle_stage"] = stage

    changed = any(item.get(key) != value for key, value in changes.items())
    item.update(changes)
    if (changed or force) and not silent:
        touch(item)

    if stage != previous_stage:
        _stage_side_effects(item, previous_stage, stage)
    return stage


def _stage_side_effects(item, previous_stage, stage):
    touched_stores = {}
    touched_seasons = {}
    if stage in ("CLEARANCE", "EXIT_PENDING"):
        for reservation in reservations_of_item(item):
            if reservation["status"] == "RESERVED":
                reservation["status"] = "COMMITTED"
                touch(reservation)
                touched_stores[reservation["store_id"]] = True
                touched_seasons[reservation["season_id"]] = True
    elif stage == "AGING" and previous_stage in ("CLEARANCE", "EXIT_PENDING"):
        for reservation in reservations_of_item(item):
            if reservation["status"] == "COMMITTED":
                reservation["status"] = "RESERVED"
                touch(reservation)
                touched_stores[reservation["store_id"]] = True
                touched_seasons[reservation["season_id"]] = True

    for store_id in touched_stores:
        store = db.get("stores", store_id)
        if store is not None:
            recompute_store(store)
    for season_id in touched_seasons:
        season = db.get("seasons", season_id)
        if season is not None:
            recompute_season(season)


def reclassify_season_items(season):
    """Re-run classification for every item of a season (PRD 3.1, 3.3)."""
    outer = _sweeping[0]
    _sweeping[0] = True
    try:
        for item in items_of_season(season):
            refresh_item(item)
    finally:
        _sweeping[0] = outer


def reclassify_all_items():
    """Re-run classification for every item in the system (PRD 2.5)."""
    outer = _sweeping[0]
    _sweeping[0] = True
    try:
        for item in sorted(db.items.values(), key=lambda r: r["created_at"]):
            refresh_item(item)
    finally:
        _sweeping[0] = outer
    for season in sorted(db.seasons.values(), key=lambda r: r["created_at"]):
        recompute_season(season)


def is_markdown_eligible(item):
    return item["lifecycle_stage"] in MARKDOWN_ELIGIBLE_STAGES


def is_disposition_eligible(item):
    return item["lifecycle_stage"] in DISPOSITION_ELIGIBLE_STAGES
