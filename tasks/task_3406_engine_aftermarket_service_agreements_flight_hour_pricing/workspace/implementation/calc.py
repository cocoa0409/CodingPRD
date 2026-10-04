"""Calculation rules (SCAFFOLD 1.3). Constants are read from the scaffold.

Money: Decimal throughout, half-up rounding at the pinned precisions.
"""
from datetime import timedelta
from decimal import Decimal

from errors import api_err
from money import round2, round4, num
from storage import DB, now
from timeutil import add_months, period_end_instant, period_index, tuple_from_index

# --- effective_rate_calculation constants ---
UTIL_BAND_LOW_THRESHOLD = Decimal("0.90")
UTIL_BAND_HIGH_THRESHOLD = Decimal("1.10")
UTIL_BAND_LOW_FACTOR = Decimal("0.95")
UTIL_BAND_STANDARD_FACTOR = Decimal("1.00")
UTIL_BAND_HIGH_FACTOR = Decimal("1.08")
NO_DATA_RATIO = Decimal("1.00")
WINDOW_MONTHS = 12

# --- shop_visit_forecast_calculation constants ---
FORECAST_DAYS_PER_MONTH = 30
CALENDAR_INTERVAL_MONTHS = 72

# --- workscope_determination_calculation constants ---
MIN_POST_VISIT_INTERVAL_MONTHS = 18

# --- parts_sourcing_selector constants ---
CLASS_COST_FACTOR = {"NEW": Decimal("1.00"), "REPAIRED": Decimal("0.70"), "USM": Decimal("0.45")}
CLASS_LEAD_DAYS = {"NEW": 7, "REPAIRED": 21, "USM": 3}
CLASS_PRIORITY = ["NEW", "REPAIRED", "USM"]  # fixed tie-break order

# --- lease_cost_calculation constants ---
LEASE_DEPOSIT_USD = Decimal("50000")

# --- shop_induction_capacity_check constant ---
SHOP_INDUCTION_DAILY_CAPACITY = 2

# --- recognition / visit-cost constants ---
LLP_RESET_CYCLES = 8000
WORKSCOPE_BASE_COST_USD = Decimal("1200000")
SEVERITY_COST_FACTOR = {
    "BENIGN": Decimal("1.00"),
    "MODERATE": Decimal("1.15"),
    "HARSH": Decimal("1.30"),
}
TARGET_MARGIN_PCT = Decimal("0.15")
MARGIN_FLOOR_PCT = Decimal("0.05")


# --------------------------------------------------------------------------
# Effective rate (escalation + utilization band)
# --------------------------------------------------------------------------

def escalation_anniversaries(anchor, period_tuple):
    """Count k >= 1 with anchor + k*12 months on or before the last day of the
    statement period (PRD 2.10)."""
    end = period_end_instant(period_tuple)
    k = 0
    while add_months(anchor, 12 * (k + 1)) <= end:
        k += 1
    return k


def utilization_ratio(engine, period_tuple):
    """12-month look-back ending at the statement period, VERIFIED reports only.
    No verified history -> exactly 1.00 (PRD 3.4)."""
    end_idx = period_index(period_tuple)
    window = {tuple_from_index(k) for k in range(end_idx - WINDOW_MONTHS + 1, end_idx + 1)}
    verified = [
        r for r in DB["reports"].values()
        if r["engine_id"] == engine["id"] and r["status"] == "VERIFIED"
        and r["period_tuple"] in window
    ]
    if not verified:
        return NO_DATA_RATIO
    total_hours = sum((r["flight_hours"] for r in verified), Decimal(0))
    months_present = len({r["period_tuple"] for r in verified})
    annualized = total_hours * 12 / months_present
    return annualized / engine["assumed_annual_hours"]


def band_factor(ratio):
    """Strict/non-strict bounds exactly as written (PRD 2.10)."""
    if ratio < UTIL_BAND_LOW_THRESHOLD:
        return UTIL_BAND_LOW_FACTOR
    if ratio <= UTIL_BAND_HIGH_THRESHOLD:
        return UTIL_BAND_STANDARD_FACTOR
    return UTIL_BAND_HIGH_FACTOR


def effective_rate(agreement, engine, period_tuple):
    """base * escalation_factor * band_factor, round-half-up to 4 dp."""
    anniversaries = escalation_anniversaries(agreement["escalation_anchor_date"], period_tuple)
    escalation_factor = (Decimal(1) + agreement["escalation_pct"]) ** anniversaries
    factor = band_factor(utilization_ratio(engine, period_tuple))
    return round4(agreement["base_rate_per_fh_usd"] * escalation_factor * factor)


# --------------------------------------------------------------------------
# Shop visit forecast / engine removal projection
# --------------------------------------------------------------------------

def cycle_based_date(engine):
    """logical clock + floor(llp_remaining / assumed_cycles_per_month * 30) days."""
    days = (engine["llp_remaining_cycles"] * FORECAST_DAYS_PER_MONTH) // engine["assumed_cycles_per_month"]
    return now() + timedelta(days=days)


def calendar_based_date(engine):
    """last COMPLETED visit's completion_date (or engine.created_at) + 72 months."""
    completed = [
        v for v in DB["visits"].values()
        if v["engine_id"] == engine["id"] and v["status"] == "COMPLETED"
    ]
    if completed:
        base = max(v["completion_date"] for v in completed)
    else:
        base = engine["created_at"]
    return add_months(base, CALENDAR_INTERVAL_MONTHS)


def forecast_visit(engine):
    """min(cycle_based, calendar_based); ties go to CYCLE_BASED."""
    cycle = cycle_based_date(engine)
    calendar = calendar_based_date(engine)
    if cycle <= calendar:
        return cycle, "CYCLE_BASED"
    return calendar, "CALENDAR_BASED"


def recompute_engine_removal(engine):
    engine["projected_next_removal_date"] = cycle_based_date(engine)


def visit_projected_cost(engine):
    return round2(WORKSCOPE_BASE_COST_USD * SEVERITY_COST_FACTOR[engine["base_severity_tier"]])


# --------------------------------------------------------------------------
# Workscope determination (due directives, mandatory append, life floor)
# --------------------------------------------------------------------------

def directive_due(directive, engine):
    """Step 1 of workscope_determination_calculation, against pre-visit state."""
    if not directive["mandatory"]:
        return False
    if directive["applicability_model"] != engine["engine_model"]:
        return False
    buffer_cycles = MIN_POST_VISIT_INTERVAL_MONTHS * engine["assumed_cycles_per_month"]
    cycles_bound = directive["compliance_cycles"]
    if cycles_bound is not None and cycles_bound <= engine["llp_remaining_cycles"] + buffer_cycles:
        return True
    date_bound = directive["compliance_date"]
    if date_bound is not None and date_bound <= add_months(now(), MIN_POST_VISIT_INTERVAL_MONTHS):
        return True
    return False


def append_due_directive_items(engine, items):
    """Step 2: append one MANDATORY_DIRECTIVE item per due directive,
    de-duplicated by directive_ref, in directive creation order."""
    present_refs = {it.get("directive_ref") for it in items if it.get("directive_ref")}
    directives = sorted(DB["directives"].values(), key=lambda d: d["_seq"])
    for d in directives:
        if d["directive_ref"] in present_refs:
            continue
        if directive_due(d, engine):
            items.append({
                "item_code": d["directive_ref"],
                "item_type": "MANDATORY_DIRECTIVE",
                "estimated_cost_usd": d["estimated_cost_usd"],
                "restores_cycles": 0,
                "directive_ref": d["directive_ref"],
            })
            present_refs.add(d["directive_ref"])
    return items


def workscope_totals(engine, items):
    """Steps 3-4: post-visit life floor (strict < 18 months), then 2-dp total."""
    restored = max((it["restores_cycles"] for it in items), default=0)
    post_visit_life = max(restored, engine["llp_remaining_cycles"])
    if post_visit_life < MIN_POST_VISIT_INTERVAL_MONTHS * engine["assumed_cycles_per_month"]:
        raise api_err(
            "ERR_INSUFFICIENT_LIFE_RESTORATION",
            "post-visit life below {} months of operation".format(MIN_POST_VISIT_INTERVAL_MONTHS),
        )
    total = round2(sum((it["estimated_cost_usd"] for it in items), Decimal(0)))
    return total, restored


def recompute_workscope_derived(workscope):
    workscope["total_cost_usd"] = round2(
        sum((it["estimated_cost_usd"] for it in workscope["items"]), Decimal(0)))
    workscope["restores_llp_cycles"] = max(
        (it["restores_cycles"] for it in workscope["items"]), default=0)


# --------------------------------------------------------------------------
# Parts sourcing selector
# --------------------------------------------------------------------------

def select_sourcing_class(requisition, agreement, override):
    """Returns (sourced_class, unit_cost) or (None, None) when nothing is
    eligible without override (caller escalates)."""
    allowed = agreement["allowed_sourcing_classes"]
    unit_costs = {c: round2(requisition["list_price_usd"] * CLASS_COST_FACTOR[c]) for c in CLASS_PRIORITY}

    def eligible(c):
        if c not in allowed:
            return False
        if override:
            return True
        return requisition["required_by_date"] >= now() + timedelta(days=CLASS_LEAD_DAYS[c])

    if override:
        best = min(allowed, key=lambda c: (unit_costs[c], CLASS_PRIORITY.index(c)))
        return best, unit_costs[best]
    eligible_classes = [c for c in CLASS_PRIORITY if eligible(c)]
    if requisition["requested_class"] in eligible_classes:
        chosen = requisition["requested_class"]
        return chosen, unit_costs[chosen]
    if eligible_classes:
        best = min(eligible_classes, key=lambda c: (unit_costs[c], CLASS_PRIORITY.index(c)))
        return best, unit_costs[best]
    return None, None


# --------------------------------------------------------------------------
# Leasing
# --------------------------------------------------------------------------

def lease_days(start, end):
    """Whole calendar days inside the half-open window [start, end)."""
    return (end - start).days


def windows_overlap(s1, e1, s2, e2):
    """Half-open overlap: windows that merely touch do not overlap."""
    return s1 < e2 and s2 < e1


def committed_parts_cost(visit):
    """Sum of quantity * unit_cost over SOURCED requisitions of non-SUPERSEDED
    workscopes of the visit."""
    total = Decimal(0)
    for w in DB["workscopes"].values():
        if w["shop_visit_id"] != visit["id"] or w["status"] == "SUPERSEDED":
            continue
        for r in DB["requisitions"].values():
            if r["workscope_id"] == w["id"] and r["status"] == "SOURCED":
                total += r["quantity"] * r["unit_cost_usd"]
    return round2(total)


# --------------------------------------------------------------------------
# Billing
# --------------------------------------------------------------------------

def compute_billing(agreement, period_tuple, variant):
    """billing_statement_calculation. variant is 'PROVISIONAL' or 'FINAL'.
    Returns (line_items, total). Per-line rounding is pinned; the total is the
    exact sum of rounded lines. Engines iterate enrolled_at ASC, created ASC."""
    statuses = {"SUBMITTED", "VERIFIED"} if variant == "PROVISIONAL" else {"VERIFIED"}
    engines = [e for e in DB["engines"].values() if e["agreement_id"] == agreement["id"]]
    engines.sort(key=lambda e: (e["enrolled_at"], e["_seq"]))
    lines = []
    total = Decimal(0)
    for engine in engines:
        report = next(
            (r for r in DB["reports"].values()
             if r["engine_id"] == engine["id"] and r["period_tuple"] == period_tuple
             and r["status"] in statuses),
            None,
        )
        if report is None:
            continue
        rate = effective_rate(agreement, engine, period_tuple)
        amount = round2(report["flight_hours"] * rate)
        total += amount
        lines.append({
            "engine_id": engine["id"],
            "hours": num(report["flight_hours"]),
            "effective_rate_per_fh_usd": num(rate),
            "line_amount_usd": num(amount),
        })
    return lines, total


def recompute_billed_to_date(agreement):
    """ISSUED statements count by provisional total; SETTLED by final total."""
    total = Decimal(0)
    for s in DB["statements"].values():
        if s["agreement_id"] != agreement["id"]:
            continue
        if s["status"] == "ISSUED":
            total += s["provisional_total_usd"]
        elif s["status"] == "SETTLED":
            total += s["final_total_usd"]
    total = round2(total)
    if total != agreement["billed_to_date_usd"]:
        agreement["billed_to_date_usd"] = total
        return True
    return False
