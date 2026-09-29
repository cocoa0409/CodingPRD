"""All 15 calculation rules from PRD §3 / SCAFFOLD §1.3.

Every rounding step happens exactly where the PRD says it happens.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from core import (
    D, add_years, clock, days_in_month, fmt_date, month_start_instant,
    next_month, parse_date, parse_instant, round_half_up, rhu_int, store,
)

# --- constants -------------------------------------------------------------
SEASONALITY_WEIGHTS = [
    D("0.0520"), D("0.0620"), D("0.0830"), D("0.0980"), D("0.1090"), D("0.1120"),
    D("0.1130"), D("0.1060"), D("0.0930"), D("0.0760"), D("0.0530"), D("0.0430"),
]
MINUTES_PER_DAY = 1440
LATE_FEE_PCT = D("0.015")
PAYMENT_TERM_DAYS = 21
ANNUAL_CREDIT_CAP_PCT = D("0.25")
DISCOUNT_RATE_ANNUAL = D("0.06")
INSTALLED_COST_PER_KW_CENTS = 320000
RELOCATION_LABOR_CENTS = 850000
RENEWAL_TERM_YEARS = 5
FICO_FLOOR = 580
FICO_CEIL = 800
FICO_HARD_MIN = 600
DEPOSIT_TIER_FICO_MIN = 620
DTI_CEIL = D("0.45")
BURDEN_TARGET_PCT = D("0.10")
CREDIT_WEIGHT_FICO = D("0.55")
CREDIT_WEIGHT_DTI = D("0.30")
CREDIT_WEIGHT_BURDEN = D("0.15")
APPROVE_SCORE_MIN = D("72.00")
DEPOSIT_SCORE_MIN = D("50.00")
DEPOSIT_MONTHS = 3
SELF_CONSUMPTION_RATIO = D("0.42")
GRANDFATHER_TERM_YEARS = 20
ANNUAL_DEPRECIATION_PCT = D("0.045")
MIN_RESIDUAL_PCT = D("0.10")
FMV_FLOOR_CENTS = 150000
RENEWAL_DISCOUNT_PCT = D("0.75")
REMOVAL_COST_PER_KW_CENTS = 45000
ROOF_PATCH_CENTS = 120000
ELECTION_WINDOW_OPEN_DAYS = 180
ELECTION_WINDOW_CLOSE_DAYS = 30
NO_ACCESS_FEE_CENTS = 12500
OM_LABOR_CENTS = 38000
MANUFACTURER_LABOR_CENTS = 52000
SEVERITY_MEDIUM_MINUTES = 1440
SEVERITY_HIGH_MINUTES = 10080
MAX_ROOF_WORK_SPAN_DAYS = 45
ROOF_WORK_BUFFER_DAYS = 3
MAX_ROOF_WORK_ORDERS_PER_YEAR = 2
MAX_CLAIM_REVISIONS = 3
MODULE_WARRANTY_YEARS = 25
INVERTER_WARRANTY_YEARS = 10


def clamp01(x):
    if x < 0:
        return D(0)
    if x > 1:
        return D(1)
    return x


# --- contract-year arithmetic ---------------------------------------------
def contract_year_raw(start_date, year, month):
    return ((year * 12 + month) - (start_date.year * 12 + start_date.month)) // 12 + 1


def current_contract_year(ag):
    start = parse_date(ag["contract_start_date"])
    today = clock.today()
    raw = contract_year_raw(start, today.year, today.month)
    hi = ag["term_years"] + 12 * ag["renewal_count"]
    return max(1, min(raw, hi))


def derive_contract_end_date(ag):
    start = parse_date(ag["contract_start_date"])
    return add_years(start, ag["term_years"]) - timedelta(days=1)


# --- escalated_billing_rate ------------------------------------------------
def escalation_factor(ag, n):
    return (D(1) + D(ag["escalator_pct"])) ** (int(n) - 1)


def escalated_rate_millicents(ag, n):
    if ag["product_type"] != "PPA":
        return 0
    base = ag.get("base_ppa_rate_per_kwh_millicents") or 0
    return rhu_int(D(base) * escalation_factor(ag, n))


def escalated_monthly_rent_cents(ag, n):
    if ag["product_type"] != "LEASE":
        return 0
    base = ag.get("base_monthly_lease_cents") or 0
    return rhu_int(D(base) * escalation_factor(ag, n))


def monthly_payment_cents(ag, n):
    if ag["product_type"] == "PPA":
        rate = escalated_rate_millicents(ag, n)
        return rhu_int(D(rate) * (D(ag["guaranteed_annual_kwh"]) / D(12)) / D(1000))
    return escalated_monthly_rent_cents(ag, n)


def annual_contract_value_cents(ag, n):
    return 12 * monthly_payment_cents(ag, n)


# --- nem_grandfathering_status --------------------------------------------
def evaluate_grandfathered(ag, tariff):
    if not tariff or not tariff.get("grandfathers_predecessors"):
        return False
    start = parse_date(ag["contract_start_date"])
    eff = parse_date(tariff["effective_from_date"])
    if not (start < eff):
        return False
    return clock.today() < add_years(start, GRANDFATHER_TERM_YEARS)


# --- interval merging helpers ---------------------------------------------
def merge_date_intervals(intervals):
    """Closed date intervals; overlaps AND zero-day-gap adjacencies merged."""
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1] + timedelta(days=1):
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def merge_instant_intervals(intervals):
    """Half-open instant intervals; overlaps and zero-length gaps merged."""
    out = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


ROOF_EXCUSING_STATUSES = ("APPROVED", "PANELS_REMOVED", "ROOF_COMPLETE", "REINSTALLED")


def excused_days_for_period(ag, period_year, period_month):
    dim = days_in_month(period_year, period_month)
    first = date(period_year, period_month, 1)
    last = date(period_year, period_month, dim)

    roof_intervals = []
    for rwo in store.roof_work_orders.values():
        if rwo["agreement_id"] != ag["id"]:
            continue
        if rwo["status"] not in ROOF_EXCUSING_STATUSES:
            continue
        s = parse_date(rwo["suspension_start_date"])
        e = parse_date(rwo["suspension_end_date"])
        if s and e:
            roof_intervals.append((s, e))
    roof_days = 0
    for s, e in merge_date_intervals(roof_intervals):
        lo = max(s, first)
        hi = min(e, last)
        if lo <= hi:
            roof_days += (hi - lo).days + 1

    span_start = month_start_instant(period_year, period_month)
    ny, nm = next_month(period_year, period_month)
    span_end = month_start_instant(ny, nm)

    outage_intervals = []
    for ev in store.outage_events.values():
        if ev["agreement_id"] != ag["id"]:
            continue
        if ev["status"] != "RESOLVED" or not ev.get("excused"):
            continue
        s = parse_instant(ev["detected_at"])
        e = parse_instant(ev.get("resolved_at"))
        if s and e:
            outage_intervals.append((s, e))
    seconds = 0
    for s, e in merge_instant_intervals(outage_intervals):
        lo = max(s, span_start)
        hi = min(e, span_end)
        if lo < hi:
            seconds += int((hi - lo).total_seconds())
    outage_minutes = seconds // 60

    ceil_days = -((-outage_minutes) // MINUTES_PER_DAY)
    return min(dim, roof_days + ceil_days), dim


# --- monthly_expected_production ------------------------------------------
def monthly_expected(ag, period_year, period_month):
    gross = rhu_int(D(ag["guaranteed_annual_kwh"]) * SEASONALITY_WEIGHTS[period_month - 1])
    excused, dim = excused_days_for_period(ag, period_year, period_month)
    availability = D(dim - excused) / D(dim)
    if availability < 0:
        availability = D(0)
    adjusted = rhu_int(D(gross) * availability)
    return gross, excused, adjusted


def period_due_date(period_year, period_month):
    last = date(period_year, period_month, days_in_month(period_year, period_month))
    return last + timedelta(days=PAYMENT_TERM_DAYS)


# --- monthly_shortfall_credit ---------------------------------------------
def shortfall_credit(ag, tariff, adjusted_expected_kwh, metered_kwh, contract_year):
    floor = rhu_int(D(adjusted_expected_kwh) * (D(1) - D(ag["guarantee_band_pct"])))
    shortfall = floor - metered_kwh if metered_kwh < floor else 0
    if ag["product_type"] == "PPA":
        rate = escalated_rate_millicents(ag, contract_year)
    else:
        rate = tariff["retail_rate_per_kwh_millicents"] if tariff else 0
    credit = rhu_int(D(shortfall) * D(rate) / D(1000))
    return floor, shortfall, rate, credit


# --- outage_severity_grade ------------------------------------------------
def elapsed_minutes(detected_at, until):
    delta = until - detected_at
    return int(delta.total_seconds() // 60)


def grade_severity(minutes):
    if minutes < SEVERITY_MEDIUM_MINUTES:
        return "LOW"
    if minutes < SEVERITY_HIGH_MINUTES:
        return "MEDIUM"
    return "HIGH"


# --- monitoring_status_projection ----------------------------------------
OPEN_OUTAGE_STATUSES = ("OPEN", "TRIAGED", "DISPATCHED")


def agreement_open_outages(agreement_id):
    return [e for e in store.outage_events.values()
            if e["agreement_id"] == agreement_id and e["status"] in OPEN_OUTAGE_STATUSES]


def derive_monitoring(ag):
    open_set = agreement_open_outages(ag["id"])
    count = len(open_set)
    if count == 0:
        status = "MONITORING_OK"
    elif any(e["status"] == "DISPATCHED" for e in open_set):
        status = "TRUCK_ROLL_DISPATCHED"
    else:
        status = "OUTAGE_OPEN"
    ag["open_outage_count"] = count
    ag["monitoring_status"] = status


def derive_excused_downtime(ag):
    total = 0
    for e in store.outage_events.values():
        if e["agreement_id"] == ag["id"] and e.get("excused") and e["status"] == "RESOLVED":
            total += e.get("downtime_minutes") or 0
    ag["excused_downtime_minutes"] = total


# --- truck_roll_cost_allocation -------------------------------------------
def allocate_truck_roll(disposition, root_cause):
    """Returns (billable_to, labor_cost_cents, excused)."""
    if disposition == "NO_ACCESS":
        return "HOMEOWNER", NO_ACCESS_FEE_CENTS, False
    if root_cause in ("INVERTER_FAULT", "MODULE_DEFECT"):
        return "PENDING_MANUFACTURER", MANUFACTURER_LABOR_CENTS, False
    if root_cause in ("STRING_FAULT", "COMMS_ONLY"):
        return "SUNRUN_OM", OM_LABOR_CENTS, True
    return "HOMEOWNER", NO_ACCESS_FEE_CENTS, False


# --- transfer_payoff_quote ------------------------------------------------
def total_term_months(ag):
    return (ag["term_years"] + ag["renewal_count"] * RENEWAL_TERM_YEARS) * 12


def term_figures(ag, closing_date):
    start = parse_date(ag["contract_start_date"])
    elapsed = ((closing_date.year * 12 + closing_date.month)
               - (start.year * 12 + start.month))
    total = total_term_months(ag)
    remaining = max(0, total - elapsed)
    return elapsed, remaining


def payoff_quote(ag, case):
    method = case["payoff_method"]
    if method == "NONE":
        return 0
    elapsed = case["elapsed_term_months"]
    remaining = case["remaining_term_months"]
    if method == "NPV_REMAINING_PAYMENTS":
        buckets = -((-remaining) // 12)
        first_open_year = elapsed // 12 + 1
        total = 0
        for k in range(1, buckets + 1):
            year_k = first_open_year + k - 1
            months_k = min(12, remaining - 12 * (k - 1))
            bucket = D(monthly_payment_cents(ag, year_k)) * D(months_k)
            divisor = (D(1) + DISCOUNT_RATE_ANNUAL) ** (k - 1)
            total += rhu_int(bucket / divisor)
        return total
    # UNAMORTIZED_SYSTEM_COST
    installed = rhu_int(D(ag["system_dc_kw"]) * D(INSTALLED_COST_PER_KW_CENTS))
    total_months = total_term_months(ag)
    frac = D(1) - (D(elapsed) / D(total_months)) if total_months else D(1)
    if frac < 0:
        frac = D(0)
    return rhu_int(D(installed) * frac) + RELOCATION_LABOR_CENTS


# --- buyer_credit_qualification ------------------------------------------
def credit_qualification(ag, buyer):
    fico = buyer["fico_score"]
    dti = D(buyer["dti_ratio"])
    fico_norm = clamp01(D(fico - FICO_FLOOR) / D(FICO_CEIL - FICO_FLOOR))
    dti_score = clamp01((DTI_CEIL - dti) / DTI_CEIL)
    burden_target = rhu_int(D(buyer["monthly_income_cents"]) * BURDEN_TARGET_PCT)
    payment = monthly_payment_cents(ag, current_contract_year(ag))
    if burden_target == 0:
        burden_ratio = D(2)
    else:
        burden_ratio = D(payment) / D(burden_target)
    burden_score = clamp01(D(2) - burden_ratio)
    raw = (CREDIT_WEIGHT_FICO * fico_norm + CREDIT_WEIGHT_DTI * dti_score
           + CREDIT_WEIGHT_BURDEN * burden_score)
    composite = round_half_up(raw * D(100), 2)

    if fico < FICO_HARD_MIN:
        decision, deposit = "DECLINED", 0
    elif composite >= APPROVE_SCORE_MIN:
        decision, deposit = "APPROVED", 0
    elif composite >= DEPOSIT_SCORE_MIN and fico >= DEPOSIT_TIER_FICO_MIN:
        decision, deposit = "APPROVED_WITH_DEPOSIT", DEPOSIT_MONTHS * payment
    else:
        decision, deposit = "DECLINED", 0
    return fico, dti, composite, decision, deposit


# --- savings_projection_annual -------------------------------------------
def savings_projection(ag, tariff):
    annual = ag["guaranteed_annual_kwh"]
    self_consumed = rhu_int(D(annual) * SELF_CONSUMPTION_RATIO)
    exported = annual - self_consumed
    grandfathered = bool(ag.get("tariff_grandfathered"))
    if grandfathered:
        eff_rate = ag.get("grandfathered_export_rate_millicents") or 0
    else:
        eff_rate = tariff["export_credit_rate_per_kwh_millicents"]
    avoided = rhu_int(D(self_consumed) * D(tariff["retail_rate_per_kwh_millicents"]) / D(1000))
    export_credit = rhu_int(D(exported) * D(eff_rate) / D(1000))
    fixed = tariff["monthly_fixed_charge_cents"] * 12
    cy = current_contract_year(ag)
    solar = 12 * monthly_payment_cents(ag, cy)
    savings = avoided + export_credit - fixed - solar
    return {
        "agreement_id": ag["id"],
        "contract_year": cy,
        "self_consumed_kwh": self_consumed,
        "exported_kwh": exported,
        "effective_export_rate_millicents": eff_rate,
        "avoided_import_cents": avoided,
        "export_credit_cents": export_credit,
        "utility_fixed_cents": fixed,
        "solar_cost_cents": solar,
        "annual_savings_cents": savings,
        "tariff_grandfathered": grandfathered,
    }


# --- end_of_term_election_pricing ----------------------------------------
def whole_years_between(start, end):
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return years


def election_window(ag):
    end = parse_date(ag["contract_end_date"])
    return (end - timedelta(days=ELECTION_WINDOW_OPEN_DAYS),
            end - timedelta(days=ELECTION_WINDOW_CLOSE_DAYS))


def installed_cost_cents(ag):
    return rhu_int(D(ag["system_dc_kw"]) * D(INSTALLED_COST_PER_KW_CENTS))


def election_pricing(ag, election_type, elected_on):
    start = parse_date(ag["contract_start_date"])
    elapsed_full_years = whole_years_between(start, elected_on)
    residual = round_half_up(D(1) - ANNUAL_DEPRECIATION_PCT * D(elapsed_full_years), 4)
    if residual < MIN_RESIDUAL_PCT:
        residual = MIN_RESIDUAL_PCT
    installed = installed_cost_cents(ag)
    final_year = ag["term_years"] + ag["renewal_count"] * RENEWAL_TERM_YEARS

    fmv = 0
    renewal_payment = 0
    removal = 0
    if election_type == "PURCHASE":
        fmv = max(FMV_FLOOR_CENTS, rhu_int(D(installed) * residual))
        amount = fmv
    elif election_type == "RENEW":
        renewal_payment = rhu_int(D(monthly_payment_cents(ag, final_year)) * RENEWAL_DISCOUNT_PCT)
        amount = renewal_payment
    else:
        removal = rhu_int(D(ag["system_dc_kw"]) * D(REMOVAL_COST_PER_KW_CENTS)) + ROOF_PATCH_CENTS
        amount = removal
    return {
        "elapsed_full_years": elapsed_full_years,
        "residual_pct": residual,
        "fair_market_value_cents": fmv,
        "renewal_monthly_payment_cents": renewal_payment,
        "removal_cost_cents": removal,
        "elected_amount_cents": amount,
    }
