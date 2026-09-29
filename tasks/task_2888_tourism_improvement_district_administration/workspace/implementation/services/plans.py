"""Work-plan compliance, the funding-ratio cascade, and program performance."""
from decimal import Decimal

import config
import store
from errors import fail
from store import rhu_cents, rhu4, set_if_changed, touch

from services import core

FORECAST_FILING_STATUSES = ("FILED", "AMENDED", "AUDITED", "CERTIFIED")


# ---------------------------------------------------------------------------
# expenditure line rollups (PRD 3.7)
# ---------------------------------------------------------------------------
CATEGORY_FIELD = {
    "ADMINISTRATION": "administration_cents",
    "CONTINGENCY_RESERVE": "contingency_reserve_cents",
    "SALES_AND_MARKETING": "sales_and_marketing_cents",
    "DESTINATION_EVENTS": "destination_events_cents",
    "CAPITAL_IMPROVEMENT": "capital_improvement_cents",
}


def rollups(lines):
    totals = dict((category, 0) for category in config.EXPENDITURE_CATEGORIES)
    for line in lines:
        totals[line["category"]] = line["amount_cents"]
    total = sum(line["amount_cents"] for line in lines)
    return total, totals


def write_rollups(plan, lines):
    total, totals = rollups(lines)
    plan["expenditure_lines"] = [dict(line) for line in lines]
    plan["total_budget_cents"] = total
    for category, field in CATEGORY_FIELD.items():
        plan[field] = totals[category]


# ---------------------------------------------------------------------------
# the revenue forecast (PRD 3.7)
# ---------------------------------------------------------------------------
def forecast_for(district, fiscal_year):
    prefix = "FY%d" % fiscal_year
    total = 0
    for period in core.periods_of_district(district["id"]):
        if not period["period_label"].startswith(prefix):
            continue
        for statement in core.statements_of_period(period["id"]):
            if statement["filing_status"] in FORECAST_FILING_STATUSES:
                total += statement["effective_assessment_cents"]
    return total


def funding_ratio_for(forecast, total_budget_cents):
    if total_budget_cents == 0:
        return Decimal("0.0000")
    return rhu4(Decimal(forecast) / Decimal(total_budget_cents))


def compute_forecast_fields(plan, district):
    """Return the pair without writing it, for pre-write compliance checks."""
    forecast = forecast_for(district, plan["fiscal_year"])
    return forecast, funding_ratio_for(forecast, plan["total_budget_cents"])


def write_forecast(plan, district):
    forecast, ratio = compute_forecast_fields(plan, district)
    plan["assessment_revenue_forecast_cents"] = forecast
    plan["funding_ratio"] = ratio
    return forecast, ratio


def recompute_committed_program_cents(plan):
    total = sum(p["committed_cents"] for p in core.programs_of_plan(plan["id"])
                if p["status"] != "CANCELLED")
    set_if_changed(plan, {"committed_program_cents": total})


# ---------------------------------------------------------------------------
# the suspension cascade (PRD 3.7 / 3.8)
# ---------------------------------------------------------------------------
def suspend_programs(plan):
    for program in core.programs_of_plan(plan["id"]):
        if program["status"] == "PLANNED":
            program["status"] = "SUSPENDED_PENDING_AMENDMENT"
            touch(program)
        elif program["status"] == "RUNNING" and not program["spend_frozen"]:
            program["spend_frozen"] = True
            touch(program)


def release_programs(plan):
    for program in core.programs_of_plan(plan["id"]):
        if program["status"] == "SUSPENDED_PENDING_AMENDMENT":
            program["status"] = "PLANNED"
            touch(program)
        elif program["status"] == "RUNNING" and program["spend_frozen"]:
            program["spend_frozen"] = False
            touch(program)


def reevaluate_plans(district):
    """Re-derive every plan's forecast; drive the current year's plan pending if short."""
    for plan in core.plans_of_district(district["id"]):
        forecast, ratio = compute_forecast_fields(plan, district)
        changed = set_if_changed(plan, {
            "assessment_revenue_forecast_cents": forecast,
            "funding_ratio": ratio,
        })
        if (plan["status"] == "APPROVED"
                and plan["fiscal_year"] == district["current_fiscal_year"]
                and ratio < config.FUNDING_RATIO_FLOOR):
            plan["status"] = "AMENDMENT_PENDING"
            touch(plan)
            suspend_programs(plan)
        elif changed:
            pass


def reevaluate_for_statement(statement):
    reevaluate_plans(core.district_of_statement(statement))


# ---------------------------------------------------------------------------
# compliance checks (PRD 3.7) — ladder rungs 12 and 13
# ---------------------------------------------------------------------------
def enforce_category_caps(plan, district):
    total = plan["total_budget_cents"]
    admin_cap = rhu_cents(Decimal(total) * config.ADMIN_CAP_PCT)
    if plan["administration_cents"] > admin_cap:
        fail("ERR_ADMIN_SHARE_EXCEEDED",
             "ADMINISTRATION may not exceed %d cents." % admin_cap)
    contingency_cap = rhu_cents(Decimal(total) * config.CONTINGENCY_CAP_PCT)
    if plan["contingency_reserve_cents"] > contingency_cap:
        fail("ERR_CONTINGENCY_SHARE_EXCEEDED",
             "CONTINGENCY_RESERVE may not exceed %d cents." % contingency_cap)
    marketing_floor = rhu_cents(Decimal(total) * config.MARKETING_FLOOR_PCT)
    if plan["sales_and_marketing_cents"] < marketing_floor:
        fail("ERR_MARKETING_SHARE_BELOW_MINIMUM",
             "SALES_AND_MARKETING must be at least %d cents." % marketing_floor)
    if (plan["capital_improvement_cents"] > 0
            and district["assessment_method"] != "PCT_OF_ROOM_REVENUE"):
        fail("ERR_EXPENDITURE_CATEGORY_NOT_PERMITTED",
             "CAPITAL_IMPROVEMENT is permitted only under PCT_OF_ROOM_REVENUE.")


def match_ceiling(plan):
    return rhu_cents(Decimal(plan["total_budget_cents"]) * config.LODGING_TAX_MATCH_CAP_PCT)


def enforce_match_ceiling(plan, district):
    ceiling = match_ceiling(plan)
    bound = min(ceiling, district["lodging_tax_match_pool_cents"])
    if district["lodging_tax_match_committed_cents"] > bound:
        fail("ERR_LODGING_TAX_MATCH_CAP_EXCEEDED",
             "Committed lodging tax match may not exceed %d cents." % bound)


def enforce_funding_ratio(plan):
    if plan["funding_ratio"] < config.FUNDING_RATIO_FLOOR:
        fail("ERR_FUNDING_RATIO_BELOW_MINIMUM",
             "funding_ratio must be at least 0.9000.")


# ---------------------------------------------------------------------------
# program performance (PRD 3.8)
# ---------------------------------------------------------------------------
def recompute_verified_nights(program):
    total = sum(c["verified_room_nights"] or 0 for c in core.claims_of_program(program["id"])
                if c["status"] == "VERIFIED")
    program["verified_room_nights"] = total
    return total


def measure_performance(program):
    """Two passes: the tier is fixed from the gross figure and never reselected."""
    nights = recompute_verified_nights(program)
    committed = program["committed_cents"]

    if nights == 0:
        gross = None
        tier = "TIER_UNPRODUCTIVE"
    else:
        gross = rhu_cents(Decimal(committed) / Decimal(nights))
        tier = "TIER_UNPRODUCTIVE"
        for bound, name in config.TIER_BOUNDS:
            if gross <= bound:
                tier = name
                break

    share = rhu_cents(Decimal(committed) * config.DMO_SHARE_PCT[tier])
    net = committed - share
    if nights == 0:
        net_cprn = None
        index = Decimal("0.0000")
    else:
        net_cprn = rhu_cents(Decimal(net) / Decimal(nights))
        if net_cprn == 0:
            index = Decimal("0.0000")
        else:
            index = rhu4(Decimal(config.BENCHMARK_CPRN_CENTS) / Decimal(net_cprn))

    if nights == 0:
        flag = "UNDERPERFORMING"
    elif index >= config.MEETS_BENCHMARK_INDEX:
        flag = "MEETS_BENCHMARK"
    elif index >= config.BELOW_BENCHMARK_INDEX:
        flag = "BELOW_BENCHMARK"
    else:
        flag = "UNDERPERFORMING"

    program["gross_cost_per_room_night_cents"] = gross
    program["efficiency_tier"] = tier
    program["dmo_cost_share_cents"] = share
    program["net_district_cost_cents"] = net
    program["net_cost_per_room_night_cents"] = net_cprn
    program["performance_index"] = index
    program["performance_flag"] = flag
