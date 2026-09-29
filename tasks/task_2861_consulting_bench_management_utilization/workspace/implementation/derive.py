"""Every derived number in the system (PRD 2.5, 2.6, 2.10 and section 3).

Nothing here is cached: each computed field is derived from the current store
and the current logical clock inside the request that reads it, which is what
makes a clock move re-derive computed fields with no batch job anywhere.
"""
from datetime import timedelta
from decimal import Decimal

from helpers import (
    day_after,
    q2,
    q4,
    workdays,
    workdays_inclusive,
)
from store import bump, db

# ------------------------------------------------------------------ constants
ASSIGNED_ALLOCATION_THRESHOLD_PCT = Decimal("50.00")
W_SKILL = Decimal("0.35")
W_INDUSTRY = Decimal("0.15")
W_DEV_GOAL = Decimal("0.15")
W_TRAVEL = Decimal("0.20")
W_COST = Decimal("0.15")
CERT_BONUS = Decimal("0.10")
INDUSTRY_FIT_FULL_YEARS = Decimal("3")
AUTO_STAFF_ALLOCATION_PCT = Decimal("100.00")
POSTURE_CONSTRAINED_RATIO = Decimal("0.3000")
POSTURE_FROZEN_RATIO = Decimal("0.5000")
POSTURE_FROZEN_L2_COUNT = 3
INTERNAL_PROJECT_MAX_DAYS = 30
WORKDAY_HOURS = Decimal("8")
MARGIN_FLOOR_PCT = Decimal("20.00")
TIER_NONE_MAX_PCT = Decimal("5.00")
TIER_L1_MAX_PCT = Decimal("15.00")
DISCOUNT_HARD_CAP_PCT = Decimal("35.00")
HIRE_YIELD_FTE = Decimal("0.85")
SUPPLY_MIN_PROFICIENCY = 3
COMMITTED_PROBABILITY_FLOOR_PCT = 70
SCARCITY_CARVE_OUT = Decimal("0.7000")

STANDARD_COST_RATE_BY_PROFICIENCY = {
    1: Decimal("45.00"),
    2: Decimal("60.00"),
    3: Decimal("80.00"),
    4: Decimal("105.00"),
    5: Decimal("130.00"),
}

LEVEL_TARGET_DEFAULTS = {
    "ANALYST": {
        "target_utilization_pct": Decimal("70.00"),
        "bench_escalation_l1_days": 21,
        "bench_escalation_l2_days": 45,
        "max_investment_pct": Decimal("20.00"),
    },
    "CONSULTANT": {
        "target_utilization_pct": Decimal("75.00"),
        "bench_escalation_l1_days": 14,
        "bench_escalation_l2_days": 30,
        "max_investment_pct": Decimal("15.00"),
    },
    "SENIOR_CONSULTANT": {
        "target_utilization_pct": Decimal("80.00"),
        "bench_escalation_l1_days": 14,
        "bench_escalation_l2_days": 28,
        "max_investment_pct": Decimal("12.00"),
    },
    "MANAGER": {
        "target_utilization_pct": Decimal("70.00"),
        "bench_escalation_l1_days": 30,
        "bench_escalation_l2_days": 60,
        "max_investment_pct": Decimal("25.00"),
    },
    "PRINCIPAL": {
        "target_utilization_pct": Decimal("55.00"),
        "bench_escalation_l1_days": 45,
        "bench_escalation_l2_days": 90,
        "max_investment_pct": Decimal("35.00"),
    },
}


def clock_date():
    return db.clock_date()


def level_target(consultant):
    """Per-key fallback (PRD 2.10): a group that supplies an entry for one level
    still uses the firm-wide defaults for every other level."""
    resolved = dict(LEVEL_TARGET_DEFAULTS[consultant["level"]])
    group = db.get("practice_groups", consultant.get("practice_group_id"))
    targets = (group or {}).get("level_targets") or {}
    entry = targets.get(consultant["level"])
    if isinstance(entry, dict):
        for key in resolved:
            if entry.get(key) is not None:
                resolved[key] = entry[key]
    return resolved


# ------------------------------------------------------------------ consultant
def assignments_of(consultant_id):
    return [a for a in db.all("assignments") if a["consultant_id"] == consultant_id]


def assignments_on(demand_id):
    return [a for a in db.all("assignments") if a["demand_opportunity_id"] == demand_id]


def placements_on(demand_id):
    return [p for p in db.all("external_placements") if p["demand_opportunity_id"] == demand_id]


def effective_end(assignment):
    if assignment["status"] == "RELEASED" and assignment.get("released_on"):
        return assignment["released_on"]
    return assignment["end_date"]


def spells_of(consultant_id):
    return [s for s in db.all("bench_spells") if s["consultant_id"] == consultant_id]


def open_spell(consultant_id):
    for spell in spells_of(consultant_id):
        if spell["state"] not in ("CLOSED", "SEPARATED"):
            return spell
    return None


def allocated_pct(consultant):
    today = clock_date()
    total = Decimal("0")
    for assignment in assignments_of(consultant["id"]):
        if assignment["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        end = effective_end(assignment)
        if assignment["start_date"] <= today < end:
            total += assignment["allocation_pct"]
    return q2(total)


def availability(consultant):
    if consultant.get("separated_on"):
        return "SEPARATED"
    spell = open_spell(consultant["id"])
    if spell is not None:
        if spell["state"] == "RESKILLING":
            return "RESKILLING"
        if spell["state"] == "INTERNAL_PROJECT":
            return "INTERNAL_PROJECT"
    if allocated_pct(consultant) >= ASSIGNED_ALLOCATION_THRESHOLD_PCT:
        return "ASSIGNED"
    return "BENCH"


def assertion_status(assertion):
    if not assertion.get("certification_code"):
        return "ACTIVE"
    expires = assertion.get("certification_expires_on")
    if expires is None:
        return "ACTIVE"
    return "ACTIVE" if expires >= clock_date() else "EXPIRED"


def assertions_for(consultant_id, skill_id):
    return [
        a
        for a in db.all("skill_assertions")
        if a["consultant_id"] == consultant_id and a["skill_id"] == skill_id
    ]


def reference_assertion(consultant_id, skill_id):
    """Highest proficiency among the consultant's ACTIVE assertions for the
    skill, ties broken by the earlier created_at."""
    active = [a for a in assertions_for(consultant_id, skill_id) if assertion_status(a) == "ACTIVE"]
    if not active:
        return None
    active.sort(key=lambda a: (-a["proficiency_level"], a["_seq"]))
    return active[0]


def spell_age_days(spell):
    base = spell.get("age_reset_on") or spell.get("started_on")
    if base is None:
        return 0
    end = spell.get("ended_on") or clock_date()
    return max(0, (end - base).days)


# -------------------------------------------------------------- practice group
def child_groups(group_id):
    return [g for g in db.all("practice_groups") if g.get("parent_group_id") == group_id]


def subtree_ids(group_id):
    """The group plus every transitive descendant."""
    seen = set()
    frontier = [group_id]
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        for child in child_groups(current):
            if child["id"] not in seen:
                frontier.append(child["id"])
    return seen


def ancestor_chain(group_id):
    """The group followed by every transitive ancestor, child-to-parent."""
    chain = []
    seen = set()
    current = group_id
    while current and current not in seen:
        group = db.get("practice_groups", current)
        if group is None:
            break
        seen.add(current)
        chain.append(group)
        current = group.get("parent_group_id")
    return chain


def group_headcounts(group_id):
    total = 0
    bench = 0
    for consultant in db.all("consultants"):
        if consultant.get("practice_group_id") != group_id:
            continue
        status = availability(consultant)
        if status == "SEPARATED":
            continue
        total += 1
        if status in ("BENCH", "RESKILLING"):
            bench += 1
    return total, bench


def escalated_l2_count(group_id):
    scope = subtree_ids(group_id)
    count = 0
    for spell in db.all("bench_spells"):
        if spell["state"] not in ("ESCALATED_L2", "SEPARATION_PROPOSED"):
            continue
        consultant = db.get("consultants", spell["consultant_id"])
        if consultant is None:
            continue
        if consultant.get("practice_group_id") in scope:
            count += 1
    return count


def group_derived(group):
    total, bench = group_headcounts(group["id"])
    roll_total = 0
    roll_bench = 0
    for gid in subtree_ids(group["id"]):
        sub_total, sub_bench = group_headcounts(gid)
        roll_total += sub_total
        roll_bench += sub_bench
    own_ratio = q4(Decimal(bench) / Decimal(total)) if total else Decimal("0.0000")
    rollup = q4(Decimal(roll_bench) / Decimal(roll_total)) if roll_total else Decimal("0.0000")
    l2 = escalated_l2_count(group["id"])
    if rollup >= POSTURE_FROZEN_RATIO or l2 >= POSTURE_FROZEN_L2_COUNT:
        posture = "FROZEN"
    elif rollup >= POSTURE_CONSTRAINED_RATIO:
        posture = "CONSTRAINED"
    else:
        posture = "OPEN"
    return {
        "total_headcount": total,
        "bench_headcount": bench,
        "escalated_l2_count": l2,
        "own_bench_ratio": own_ratio,
        "rollup_bench_ratio": rollup,
        "posture": posture,
    }


def group_posture(group_id):
    group = db.get("practice_groups", group_id)
    if group is None:
        return "OPEN"
    return group_derived(group)["posture"]


def derived_snapshot():
    """Snapshot of every group's derived tuple, used to give a practice group a
    fresh updated_at/version whenever a request moved one of those numbers."""
    return {group["id"]: tuple(sorted(group_derived(group).items())) for group in db.all("practice_groups")}


# --------------------------------------------------------------------- demand
def effective_rate(demand):
    if demand.get("approved_rate_usd_per_hour") is not None:
        return demand["approved_rate_usd_per_hour"]
    return demand["requested_rate_usd_per_hour"]


def weighted_fte(demand):
    return q2(demand["required_fte"] * Decimal(demand["win_probability_pct"]) / Decimal(100))


def coverage(demand):
    internal = Decimal("0")
    for assignment in assignments_on(demand["id"]):
        if assignment["status"] in ("CONFIRMED", "ACTIVE"):
            internal += assignment["allocation_pct"]
    covered_internal = q2(internal / Decimal(100))
    external = Decimal("0")
    for placement in placements_on(demand["id"]):
        if placement["status"] in ("APPROVED", "ACTIVE"):
            external += placement["fte"]
    covered_external = q2(external)
    open_fte = q2(max(Decimal("0.00"), demand["required_fte"] - covered_internal - covered_external))
    total = covered_internal + covered_external
    if total > 0 and open_fte == 0:
        status = "COVERED"
    elif total > 0:
        status = "PARTIALLY_COVERED"
    elif demand.get("staffing_mode") == "INTERNAL":
        status = "INTERNAL_STAFFING"
    elif demand.get("staffing_mode") == "EXTERNAL":
        status = "EXTERNAL_SOURCING"
    else:
        status = "UNSTAFFED"
    return {
        "covered_internal_fte": covered_internal,
        "covered_external_fte": covered_external,
        "open_fte": open_fte,
        "staffing_status": status,
    }


def delivered_workdays(assignment, today=None):
    """Mon-Fri dates from start_date inclusive up to but excluding the earlier of
    the effective end and the day after the logical clock date."""
    if today is None:
        today = clock_date()
    right = min(effective_end(assignment), day_after(today))
    return workdays(assignment["start_date"], right)


def delivered_hours(assignment, today=None):
    count = delivered_workdays(assignment, today)
    return (assignment["allocation_pct"] / Decimal(100)) * Decimal(count) * WORKDAY_HOURS


def committed_rows(demand):
    return [
        a
        for a in assignments_on(demand["id"])
        if a["status"] in ("CONFIRMED", "ACTIVE", "RELEASED")
    ]


def realization(demand, extra=None):
    """Booked and earned realization, blended cost and margin (PRD 3.7).

    `extra` optionally adds a candidate assignment row that has not been written
    yet, which is how the margin floor is projected on confirmation."""
    rate = effective_rate(demand)
    standard = demand["standard_rate_usd_per_hour"]
    booked = q2(Decimal(100) * rate / standard)
    rows = committed_rows(demand)
    if extra is not None:
        rows = rows + [extra]
    total_hours = Decimal("0")
    bill_weighted = Decimal("0")
    cost_weighted = Decimal("0")
    for assignment in rows:
        hours = delivered_hours(assignment)
        total_hours += hours
        bill_weighted += assignment["bill_rate_usd_per_hour"] * hours
        cost_weighted += assignment["cost_rate_usd_per_hour"] * hours
    if total_hours == 0:
        earned = None
        blended_cost = Decimal("0.00")
    else:
        earned = q2(Decimal(100) * bill_weighted / (standard * total_hours))
        blended_cost = q2(cost_weighted / total_hours)
    if blended_cost == 0:
        margin = None
    else:
        margin = q2(Decimal(100) * (rate - blended_cost) / rate)
    return {
        "booked_realization_pct": booked,
        "earned_realization_pct": earned,
        "blended_cost_rate_usd_per_hour": blended_cost,
        "blended_margin_pct": margin,
        "margin_breach": margin is not None and margin < MARGIN_FLOOR_PCT,
    }


# ---------------------------------------------------------------- match score
def travel_fit(consultant, demand):
    if demand["onsite_nights_per_week"] > consultant["travel_max_nights_per_week"]:
        return Decimal("0.0000")
    if demand.get("is_international") and not consultant.get("travel_willing_international"):
        return Decimal("0.0000")
    return q4(Decimal(1) - Decimal(demand["onsite_nights_per_week"]) / Decimal(5))


def industry_years(consultant, industry_code):
    for entry in consultant.get("industry_experience") or []:
        if entry["industry_code"] == industry_code:
            return entry["years"]
    return Decimal("0")


def match_score(consultant, demand):
    if availability(consultant) in ("RESKILLING", "SEPARATED"):
        return Decimal("0.0000")
    reference = reference_assertion(consultant["id"], demand["required_skill_id"])
    skill_fit = q4(Decimal(reference["proficiency_level"]) / Decimal(5)) if reference else Decimal("0.0000")
    years = industry_years(consultant, demand["industry_code"])
    industry_fit = q4(min(Decimal(1), years / INDUSTRY_FIT_FULL_YEARS))
    dev_goal_fit = (
        Decimal("1.0000")
        if consultant.get("development_goal_skill_id") == demand["required_skill_id"]
        else Decimal("0.0000")
    )
    travel = travel_fit(consultant, demand)
    standard = demand["standard_rate_usd_per_hour"]
    raw_cost = (standard - consultant["cost_rate_usd_per_hour"]) / standard
    cost_fit = q4(max(Decimal(0), min(Decimal(1), raw_cost)))
    bonus = Decimal("0.0000")
    if reference is not None and reference.get("certification_code") and assertion_status(reference) == "ACTIVE":
        bonus = CERT_BONUS
    raw = (
        W_SKILL * skill_fit
        + W_INDUSTRY * industry_fit
        + W_DEV_GOAL * dev_goal_fit
        + W_TRAVEL * travel
        + W_COST * cost_fit
        + bonus
    )
    return min(Decimal("1.0000"), q4(raw))


def peak_allocation(consultant_id, start, end_exclusive, exclude_id=None):
    """Maximum committed allocation over the dates of a half-open interval."""
    if start is None or end_exclusive is None or end_exclusive <= start:
        return Decimal("0.00")
    rows = [
        a
        for a in assignments_of(consultant_id)
        if a["status"] in ("CONFIRMED", "ACTIVE") and a["id"] != exclude_id
    ]
    candidates = {start}
    for row in rows:
        if start < row["start_date"] < end_exclusive:
            candidates.add(row["start_date"])
    peak = Decimal("0")
    for day in candidates:
        total = Decimal("0")
        for row in rows:
            if row["start_date"] <= day < effective_end(row):
                total += row["allocation_pct"]
        if total > peak:
            peak = total
    return q2(peak)


def auto_staff_candidates(demand):
    scope = subtree_ids(demand["practice_group_id"])
    window_end = day_after(demand["end_date"])
    candidates = []
    for consultant in db.all("consultants"):
        if consultant.get("practice_group_id") not in scope:
            continue
        if availability(consultant) not in ("BENCH", "INTERNAL_PROJECT"):
            continue
        reference = None
        for assertion in assertions_for(consultant["id"], demand["required_skill_id"]):
            if assertion_status(assertion) != "ACTIVE":
                continue
            if assertion["proficiency_level"] >= demand["min_proficiency_level"]:
                reference = assertion
                break
        if reference is None:
            continue
        if travel_fit(consultant, demand) <= 0:
            continue
        peak = peak_allocation(consultant["id"], demand["start_date"], window_end)
        if Decimal("100.00") - peak < AUTO_STAFF_ALLOCATION_PCT:
            continue
        candidates.append(consultant)
    return candidates


def rank_candidates(demand, candidates):
    def sort_key(consultant):
        spell = open_spell(consultant["id"])
        age = spell_age_days(spell) if spell else 0
        return (
            -match_score(consultant, demand),
            consultant["cost_rate_usd_per_hour"],
            -age,
            consultant["_seq"],
        )

    return sorted(candidates, key=sort_key)


# ---------------------------------------------------------- utilization period
def overlap_workdays(left_start, right_end_exclusive, period):
    """Mon-Fri dates of an interval clipped into an inclusive period."""
    start = max(left_start, period["period_start_on"])
    end = min(right_end_exclusive, day_after(period["period_end_on"]))
    return workdays(start, end)


def period_buckets(period):
    consultant_id = period["consultant_id"]
    workday_count = workdays_inclusive(period["period_start_on"], period["period_end_on"])
    capacity = q2(Decimal(workday_count) * WORKDAY_HOURS)
    net_available = q2(capacity - period["holiday_hours"])
    billable = Decimal("0")
    investment = Decimal("0")
    for assignment in assignments_of(consultant_id):
        if assignment["status"] not in ("CONFIRMED", "ACTIVE", "RELEASED"):
            continue
        days = overlap_workdays(assignment["start_date"], effective_end(assignment), period)
        hours = (assignment["allocation_pct"] / Decimal(100)) * Decimal(days) * WORKDAY_HOURS
        if assignment["category"] == "BILLABLE":
            billable += hours
        else:
            investment += hours
    for spell in spells_of(consultant_id):
        started = spell.get("investment_started_on")
        if started is None:
            continue
        ended = spell.get("investment_ended_on")
        right = ended if ended is not None else day_after(period["period_end_on"])
        days = overlap_workdays(started, right, period)
        investment += Decimal(days) * WORKDAY_HOURS
    billable = q2(billable)
    investment = q2(investment)
    bench = q2(max(Decimal("0.00"), net_available - billable - investment))
    overallocated = (billable + investment) > net_available
    available_basis = None if net_available == 0 else q2(Decimal(100) * billable / net_available)
    target_basis = None if capacity == 0 else q2(Decimal(100) * billable / capacity)
    return {
        "period_workdays": workday_count,
        "capacity_hours": capacity,
        "net_available_hours": net_available,
        "billable_hours": billable,
        "investment_hours": investment,
        "bench_hours": bench,
        "hour_overallocated": overallocated,
        "utilization_pct_available_basis": available_basis,
        "utilization_pct_target_basis": target_basis,
    }


def period_metrics(period):
    """Live buckets while OPEN; the snapshot frozen at close afterwards."""
    if period["status"] == "CLOSED":
        metrics = dict(period["_snapshot"])
    else:
        metrics = period_buckets(period)
    if period["status"] == "CLOSED":
        of_record = metrics["utilization_pct_target_basis"]
    else:
        of_record = metrics["utilization_pct_available_basis"]
    metrics["utilization_pct_of_record"] = of_record
    if of_record is None:
        metrics["variance_pp"] = None
    else:
        metrics["variance_pp"] = q2(of_record - period["target_utilization_pct"])
    return metrics


def periods_of(consultant_id):
    return [p for p in db.all("utilization_periods") if p["consultant_id"] == consultant_id]


# ------------------------------------------------------------ discount pass
def mix_rows(demand):
    return [a for a in assignments_on(demand["id"]) if a["status"] in ("CONFIRMED", "ACTIVE")]


def discount_pass(approval, demand, steps=7):
    """The single ordered pass of PRD 3.7. `steps=6` re-runs a revision, which
    stops before the auto-approval step."""
    standard = approval["standard_rate_usd_per_hour"]
    requested = approval["requested_rate_usd_per_hour"]
    approval["discount_pct"] = q2(Decimal(100) * (standard - requested) / standard)
    approval["provisional_realization_pct"] = q2(Decimal(100) * requested / standard)
    rows = mix_rows(demand)
    if rows:
        total_hours = Decimal("0")
        weighted = Decimal("0")
        for assignment in rows:
            hours = delivered_hours(assignment)
            total_hours += hours
            weighted += assignment["cost_rate_usd_per_hour"] * hours
        if total_hours == 0:
            total_alloc = sum((a["allocation_pct"] for a in rows), Decimal("0"))
            weighted = sum(
                (a["cost_rate_usd_per_hour"] * a["allocation_pct"] for a in rows), Decimal("0")
            )
            blended = q2(weighted / total_alloc) if total_alloc else Decimal("0.00")
        else:
            blended = q2(weighted / total_hours)
    else:
        blended = STANDARD_COST_RATE_BY_PROFICIENCY[demand["min_proficiency_level"]]
    approval["blended_cost_rate_usd_per_hour"] = blended
    approval["projected_margin_pct"] = q2(Decimal(100) * (requested - blended) / requested)
    discount = approval["discount_pct"]
    if discount <= TIER_NONE_MAX_PCT:
        tier = "NONE"
    elif discount <= TIER_L1_MAX_PCT:
        tier = "L1_PRACTICE_PARTNER"
    else:
        tier = "L2_FINANCE"
    approval["required_tier"] = tier
    if approval["projected_margin_pct"] < MARGIN_FLOOR_PCT and tier != "L2_FINANCE":
        approval["required_tier"] = "L2_FINANCE"
        approval["tier_escalated"] = True
    else:
        approval["tier_escalated"] = False
    if steps < 7:
        return False
    if approval["required_tier"] == "NONE":
        approval["status"] = "APPROVED"
        approval["decided_by_user_id"] = "SYSTEM_AUTO"
        return True
    approval["status"] = "PENDING"
    return False


def apply_rate_cascade(demand, rate):
    """Hops one to four of the rate cascade (PRD 3.7)."""
    demand["approved_rate_usd_per_hour"] = rate
    for assignment in assignments_on(demand["id"]):
        if assignment["status"] in ("PROPOSED", "CONFIRMED", "ACTIVE") and assignment["category"] == "BILLABLE":
            if assignment["bill_rate_usd_per_hour"] != rate:
                assignment["bill_rate_usd_per_hour"] = rate
                bump(assignment)


# ------------------------------------------------------------------ forecast
def forecast_scope(skill_code, geography_code, horizon_start, horizon_end):
    rows = []
    for demand in db.all("demand_opportunities"):
        if demand["pipeline_status"] != "QUALIFIED":
            continue
        skill = db.get("skills", demand["required_skill_id"])
        if skill is None or skill["code"] != skill_code:
            continue
        group = db.get("practice_groups", demand["practice_group_id"])
        if group is None or group["geography_code"] != geography_code:
            continue
        if demand["start_date"] > horizon_end or demand["end_date"] < horizon_start:
            continue
        rows.append(demand)
    return rows


def compute_forecast(skill_code, geography_code, horizon_start, horizon_end, basis):
    demands = forecast_scope(skill_code, geography_code, horizon_start, horizon_end)
    total = Decimal("0")
    for demand in demands:
        if basis == "COMMITTED":
            if demand["win_probability_pct"] < COMMITTED_PROBABILITY_FLOOR_PCT:
                continue
            total += q2(demand["required_fte"])
        else:
            total += q2(weighted_fte(demand))
    weighted_demand = q2(total)

    internal = Decimal("0")
    skill_ids = {s["id"] for s in db.all("skills") if s["code"] == skill_code}
    for consultant in db.all("consultants"):
        group = db.get("practice_groups", consultant.get("practice_group_id"))
        if group is None or group["geography_code"] != geography_code:
            continue
        if availability(consultant) not in ("BENCH", "INTERNAL_PROJECT"):
            continue
        qualified = False
        for assertion in db.all("skill_assertions"):
            if assertion["consultant_id"] != consultant["id"]:
                continue
            if assertion["skill_id"] not in skill_ids:
                continue
            if assertion["proficiency_level"] < SUPPLY_MIN_PROFICIENCY:
                continue
            if assertion_status(assertion) == "ACTIVE":
                qualified = True
                break
        if not qualified:
            continue
        internal += q2((Decimal(100) - allocated_pct(consultant)) / Decimal(100))
    internal_supply = q2(internal)

    scope_ids = {demand["id"] for demand in demands}
    external = Decimal("0")
    for placement in db.all("external_placements"):
        if placement["status"] not in ("APPROVED", "ACTIVE"):
            continue
        if placement["demand_opportunity_id"] in scope_ids:
            external += placement["fte"]
    external_supply = q2(external)

    gap = q2(weighted_demand - internal_supply - external_supply)
    if gap <= 0:
        hires = 0
    else:
        exact = gap / HIRE_YIELD_FTE
        hires = int(-((-exact).to_integral_value(rounding="ROUND_FLOOR")))
    return {
        "weighted_demand_fte": weighted_demand,
        "internal_supply_fte": internal_supply,
        "external_supply_fte": external_supply,
        "gap_fte": gap,
        "recommended_hires": hires,
    }
