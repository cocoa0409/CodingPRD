"""Season exit scorecard aggregation (PRD 3.9)."""

from common import dec, r2
from db import db
from services.lifecycle import (claims_of_plan, dispositions_of_season,
                                executions_of_plan, items_of_season,
                                plans_of_season, sales_weeks_of_item)


def _common_totals(season):
    items = items_of_season(season)
    units_received = sum(i["units_received_total"] for i in items)
    units_sold = sum(i["units_sold_total"] for i in items)
    units_disposed = sum(i["units_disposed_total"] for i in items)
    revenue = 0
    for item in items:
        for week in sales_weeks_of_item(item):
            revenue += week["units_sold"] * week["ticket_price_cents"]
    cogs = sum(i["units_sold_total"] * i["unit_cost_cents"] for i in items)
    return items, units_received, units_sold, units_disposed, revenue, cogs


def _projected_markdown(season):
    """PRELIMINARY: frozen lines for APPLIED, marked-to-market for SCHEDULED."""
    markdown_reserve = 0
    promo_discount = 0
    for plan in plans_of_season(season):
        item = db.get("items", plan["item_id"])
        for execution in executions_of_plan(plan):
            if execution["status"] == "APPLIED":
                line = execution["line_markdown_cents"]
            elif execution["status"] == "SCHEDULED":
                step = db.get("steps", execution["markdown_step_id"])
                if step is None or item is None:
                    continue
                line = (item["current_retail_cents"] - step["price_cents"]) * \
                    execution["units_in_scope"]
            else:
                continue
            if plan["plan_type"] == "PERMANENT":
                markdown_reserve += line
            else:
                promo_discount += line
    return markdown_reserve, promo_discount


def _projected_vendor_funding(season):
    total = 0
    for plan in plans_of_season(season):
        for claim in claims_of_plan(plan):
            if claim["status"] == "SUBMITTED":
                total += claim["claimed_cents"]
            elif claim["status"] == "RECOGNIZED":
                total += claim["recognized_cents"]
    return total


def _final_vendor_funding(season):
    total = 0
    for plan in plans_of_season(season):
        for claim in claims_of_plan(plan):
            if claim["status"] == "RECOGNIZED":
                total += claim["recognized_cents"]
    return total


def _projected_disposition_recovery(season):
    total = 0
    for order in dispositions_of_season(season):
        if order["status"] in ("DRAFT", "APPROVED"):
            total += order["projected_recovery_cents"]
        elif order["status"] == "SETTLED":
            total += order["settled_recovery_cents"]
    return total


def _final_disposition_recovery(season):
    return sum(o["settled_recovery_cents"]
               for o in dispositions_of_season(season)
               if o["status"] == "SETTLED")


def build_scorecard(season, review_type):
    items, units_received, units_sold, units_disposed, revenue, cogs = \
        _common_totals(season)

    if review_type == "PRELIMINARY":
        markdown_reserve, promo_discount = _projected_markdown(season)
        vendor_funding = _projected_vendor_funding(season)
        disposition_recovery = _projected_disposition_recovery(season)
    else:
        markdown_reserve = sum(i["permanent_markdown_reserve_cents"]
                               for i in items)
        promo_discount = sum(i["promo_discount_cents"] for i in items)
        vendor_funding = _final_vendor_funding(season)
        disposition_recovery = _final_disposition_recovery(season)

    sell_through = r2(dec(units_sold) / dec(units_received) * dec(100)) \
        if units_received else r2(0)
    gross_margin = revenue - cogs - markdown_reserve - promo_discount + \
        vendor_funding + disposition_recovery

    return {
        "revenue_cents": revenue,
        "cogs_cents": cogs,
        "markdown_reserve_cents": markdown_reserve,
        "promo_discount_cents": promo_discount,
        "vendor_funding_cents": vendor_funding,
        "disposition_recovery_cents": disposition_recovery,
        "gross_margin_cents": gross_margin,
        "sell_through_pct": sell_through,
        "units_received_total": units_received,
        "units_sold_total": units_sold,
        "units_disposed_total": units_disposed,
        "exit_units_variance": (units_sold + units_disposed) -
                               season["exit_units_target"],
        "sell_through_variance_pct": r2(
            dec(sell_through) - dec(season["sell_through_target_pct"])),
    }
