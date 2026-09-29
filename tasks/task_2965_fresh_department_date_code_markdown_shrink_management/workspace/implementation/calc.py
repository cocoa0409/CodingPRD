"""Calculation rules (SCAFFOLD 1.3 / PRD section 2.6, 2.9, 2.10 and 3.x).

Every money and percentage figure is computed with Decimal and ROUND_HALF_UP.
"""
import math

from db import db, ordered
from errors import ApiError
from records import (department_of_item, department_of_lot, item_of_lot,
                     labels_of_lot, lots_of_department, lots_of_item,
                     shrink_events_of_lot)
from util import (COST_FLOOR_PCT, D, ORDER_HORIZON_DAYS, PROMO_LIFT_PCT,
                  SELL_THROUGH_STEP_PCT, SEVERITY_TIER_2_HOURS,
                  SHRINK_LOOKBACK_DAYS, WASTE_HANDLING_PCT, add_seconds,
                  end_of_day_utc, floor_div_seconds, midnight_utc, num,
                  parse_instant, rhu2, rhu_int, round_half_up)

PROFILE_MULTIPLIER = {
    "STANDARD": D("1.00"),
    "AGGRESSIVE": D("1.25"),
    "CONSERVATIVE": D("0.80"),
}

LIABILITY_STATUSES = ("FRESH", "MARKED_DOWN", "DONATION_PENDING")
COUNTED_SHRINK_STATUSES = ("VERIFIED", "POSTED")
FORECAST_CAUSE_CODES = ("SPOILAGE", "DAMAGE", "THEFT")


# --- sell_by_instant --------------------------------------------------------
def effective_shelf_life_days(item, department):
    if item.get("shelf_life_days") is not None:
        return item["shelf_life_days"]
    return department["shelf_life_days_default"]


def sell_by_instant(production_date, shelf_life_days):
    return add_seconds(midnight_utc(production_date), shelf_life_days * 86400)


# --- days_remaining --------------------------------------------------------
def days_remaining(lot):
    sell_by = parse_instant(lot["sell_by_at"])
    return floor_div_seconds((sell_by - db.now()).total_seconds(), 86400)


def hours_past_date(lot):
    sell_by = parse_instant(lot["sell_by_at"])
    return floor_div_seconds((db.now() - sell_by).total_seconds(), 3600)


# --- expected_sell_through -------------------------------------------------
def has_applied_label(lot):
    for label in labels_of_lot(lot["id"]):
        if label["status"] == "APPLIED":
            return True
    return False


def expected_sell_through(lot, item=None, department=None):
    item = item or item_of_lot(lot)
    department = department or department_of_item(item)
    on_hand = lot["quantity_on_hand"]
    if on_hand <= 0:
        return 0
    multiplier = PROFILE_MULTIPLIER[department["markdown_policy_profile"]]
    promo_lift = D(0)
    if has_applied_label(lot):
        promo_lift = D(on_hand) * PROMO_LIFT_PCT / D(100)
    horizon = max(days_remaining(lot), 0)
    projected = D(item["daily_forecast_units"]) * multiplier * D(horizon)
    projected = projected + promo_lift
    pct = round_half_up(projected / D(on_hand) * D(100), 2)
    if pct > D(100):
        pct = D(100)
    return num(pct)


# --- ladder_rung_selection -------------------------------------------------
def base_rung_index(ladder, remaining):
    candidates = [
        index for index, rung in enumerate(ladder["rungs"])
        if remaining <= rung["days_remaining_max"]
    ]
    return max(candidates) if candidates else -1


def shortfall_steps(ladder, expected_pct):
    floor_pct = D(ladder["sell_through_floor_pct"])
    current = D(expected_pct)
    if current >= floor_pct:
        return 0
    gap = (floor_pct - current) / SELL_THROUGH_STEP_PCT
    return int(math.ceil(gap))


# --- markdown_price --------------------------------------------------------
def cost_floor_price_cents(item):
    return rhu_int(D(item["unit_cost_cents"]) * COST_FLOOR_PCT / D(100))


def total_discount_pct(item, to_price_cents):
    base = D(item["base_retail_cents"])
    return rhu2((base - D(to_price_cents)) / base * D(100))


def price_at_rung(item, ladder, rung_index):
    discount = D(ladder["rungs"][rung_index]["discount_pct"])
    raw = D(item["base_retail_cents"]) * (D(1) - discount / D(100))
    to_price = max(cost_floor_price_cents(item), rhu_int(raw))
    return to_price, total_discount_pct(item, to_price)


# --- lot_unit_conservation -------------------------------------------------
def conservation_holds(lot):
    return lot["quantity_original"] == (
        lot["quantity_on_hand"] + lot["units_sold"]
        + lot["units_shrunk"] + lot["units_donated"]
    )


# --- markdown_liability ----------------------------------------------------
def markdown_liability_cents(department):
    total = 0
    for lot in lots_of_department(department["id"]):
        if lot["status"] not in LIABILITY_STATUSES:
            continue
        item = item_of_lot(lot)
        total += lot["quantity_on_hand"] * (
            item["base_retail_cents"] - lot["current_price_cents"]
        )
    return total


# --- gross_margin_impact / shrink_cost_ratio -------------------------------
def _waste_line(units, unit_cost_cents):
    return rhu_int(
        D(units) * D(unit_cost_cents) * (D(1) + WASTE_HANDLING_PCT / D(100))
    )


def margin_lines(lots):
    """Round every per-lot line first, then sum the rounded lines."""
    revenue = 0
    giveback = 0
    cogs = 0
    shrink = 0
    donation = 0
    for lot in ordered(lots):
        item = item_of_lot(lot)
        unit_cost = item["unit_cost_cents"]
        revenue += lot["revenue_cents"]
        giveback += lot["markdown_giveback_cents"]
        cogs += _waste_line(lot["units_sold"], unit_cost)
        shrink += _waste_line(lot["units_shrunk"], unit_cost)
        donation += _waste_line(lot["units_donated"], unit_cost)
    return {
        "revenue_cents": revenue,
        "markdown_giveback_cents": giveback,
        "cogs_cents": cogs,
        "shrink_cost_cents": shrink,
        "donation_cost_cents": donation,
    }


def margin_totals(lines):
    revenue = lines["revenue_cents"]
    cogs = lines["cogs_cents"]
    shrink = lines["shrink_cost_cents"]
    donation = lines["donation_cost_cents"]
    gross_margin = revenue - cogs - shrink - donation
    result = dict(lines)
    result["gross_margin_cents"] = gross_margin
    if revenue > 0:
        result["gross_margin_pct"] = rhu2(D(gross_margin) / D(revenue) * D(100))
    else:
        result["gross_margin_pct"] = 0
    denominator = cogs + shrink + donation
    if denominator > 0:
        result["shrink_cost_ratio_pct"] = rhu2(
            D(shrink) / D(denominator) * D(100)
        )
    else:
        result["shrink_cost_ratio_pct"] = 0
    return result


def lots_created_between(lots, start_instant, end_instant):
    selected = []
    for lot in lots:
        created = parse_instant(lot["created_at"])
        if start_instant <= created <= end_instant:
            selected.append(lot)
    return selected


def margin_report_for_department(department, start_date, end_date):
    window = lots_created_between(
        lots_of_department(department["id"]),
        midnight_utc(start_date),
        end_of_day_utc(end_date),
    )
    totals = margin_totals(margin_lines(window))
    totals["lot_count"] = len(window)
    return totals


def shrink_cost_ratio_pct(department):
    now = db.now()
    window = lots_created_between(
        lots_of_department(department["id"]),
        add_seconds(now, -SHRINK_LOOKBACK_DAYS * 86400),
        now,
    )
    lines = margin_lines(window)
    shrink = lines["shrink_cost_cents"]
    denominator = (
        lines["cogs_cents"] + shrink + lines["donation_cost_cents"]
    )
    if denominator <= 0:
        return 0
    return rhu2(D(shrink) / D(denominator) * D(100))


# --- compliance_severity ---------------------------------------------------
def severity_multiplier(hours, tolerance_hours):
    if hours <= tolerance_hours:
        return 1
    if hours <= SEVERITY_TIER_2_HOURS:
        return 3
    return 6


def severity_band(points_total):
    if points_total == 0:
        return "NONE"
    if 1 <= points_total <= 9:
        return "MINOR"
    if 10 <= points_total <= 29:
        return "MAJOR"
    return "CRITICAL"


def past_date_lots_on_shelf(department):
    now = db.now()
    selected = []
    for lot in lots_of_department(department["id"]):
        if lot["status"] not in LIABILITY_STATUSES:
            continue
        if lot["quantity_on_hand"] <= 0:
            continue
        if now >= parse_instant(lot["sell_by_at"]):
            selected.append(lot)
    return ordered(selected)


# --- donation_manifest_valuation -------------------------------------------
def credit_rate_for(provisional_value_cents):
    from util import (CREDIT_RATE_TIER_1_PCT, CREDIT_RATE_TIER_2_PCT,
                      CREDIT_RATE_TIER_3_PCT, TIER_2_FLOOR_CENTS,
                      TIER_3_FLOOR_CENTS)
    if provisional_value_cents < TIER_2_FLOOR_CENTS:
        return CREDIT_RATE_TIER_1_PCT
    if provisional_value_cents < TIER_3_FLOOR_CENTS:
        return CREDIT_RATE_TIER_2_PCT
    return CREDIT_RATE_TIER_3_PCT


# --- shrink_history_order_feedback ----------------------------------------
def order_feedback(item, start_date, end_date, method):
    all_lots = lots_of_item(item["id"])
    window_lots = lots_created_between(
        all_lots, midnight_utc(start_date), end_of_day_utc(end_date)
    )
    received_units = sum(lot["quantity_original"] for lot in window_lots)
    if received_units == 0:
        raise ApiError(
            "ERR_INSUFFICIENT_SHRINK_HISTORY",
            "No lots of this item were received inside the window",
        )
    shrink_units = 0
    for lot in ordered(window_lots):
        for event in shrink_events_of_lot(lot["id"]):
            if event["cause_code"] not in FORECAST_CAUSE_CODES:
                continue
            if event["status"] in COUNTED_SHRINK_STATUSES:
                shrink_units += event["quantity_units"]
            elif (method == "FORWARD_LOOKING_PROJECTED"
                    and event["status"] == "RECORDED"):
                shrink_units += event["quantity_units"]
    if method == "FORWARD_LOOKING_PROJECTED":
        for lot in ordered(all_lots):
            if lot["status"] not in ("FRESH", "MARKED_DOWN"):
                continue
            expected_sales = rhu_int(
                D(item["daily_forecast_units"]) * D(max(days_remaining(lot), 0))
            )
            projected_loss = lot["quantity_on_hand"] - expected_sales
            if projected_loss > 0:
                shrink_units += projected_loss
    rate = round_half_up(D(shrink_units) / D(received_units) * D(100), 2)
    open_units = 0
    for lot in all_lots:
        if lot["status"] in ("FRESH", "MARKED_DOWN"):
            open_units += lot["quantity_on_hand"]
    recommended = rhu_int(
        D(item["daily_forecast_units"]) * D(ORDER_HORIZON_DAYS)
        * (D(1) - rate / D(100))
        - D(open_units)
    )
    return {
        "received_units": received_units,
        "shrink_units": shrink_units,
        "shrink_rate_pct": num(rate),
        "open_units": open_units,
        "recommended_order_units": max(0, recommended),
    }
