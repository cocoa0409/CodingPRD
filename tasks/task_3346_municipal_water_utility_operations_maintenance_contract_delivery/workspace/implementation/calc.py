"""The calculation rules of PRD 3.  Pure functions over the in-memory store."""
import math
from datetime import timedelta

from core import DB, dec, f2, f4, icents, now, parse_dt, rhu

# --------------------------------------------------------------------------
# condition band — a pure function of the score, shared system wide
# --------------------------------------------------------------------------
BAND_EXCELLENT = 80.0
BAND_GOOD = 60.0
BAND_FAIR = 40.0
BAND_POOR = 20.0


def condition_band(score):
    s = rhu(dec(score), 1)
    if s >= dec(BAND_EXCELLENT):
        return "EXCELLENT"
    if s >= dec(BAND_GOOD):
        return "GOOD"
    if s >= dec(BAND_FAIR):
        return "FAIR"
    if s >= dec(BAND_POOR):
        return "POOR"
    return "CRITICAL"


def condition_at_least(score, threshold):
    """Condition scores and their thresholds are compared at 1 decimal place."""
    return rhu(dec(score), 1) >= rhu(dec(threshold), 1)


def condition_below(score, threshold):
    return rhu(dec(score), 1) < rhu(dec(threshold), 1)


# --------------------------------------------------------------------------
# 1. staffing floor
# --------------------------------------------------------------------------
def staffing_floor_fte(contract_id):
    active = [s for s in DB["standards"].values()
              if s["contract_id"] == contract_id and s["status"] == "ACTIVE"]
    weights = sum((dec(s["criticality_weight"]) for s in active), dec(0))
    base = rhu(dec("0.5") * len(active) + dec("0.25") * weights, 2)
    if base >= dec("6.00"):
        surcharge = dec("3.00")
    elif base >= dec("3.50"):
        surcharge = dec("2.00")
    elif base >= dec("1.50"):
        surcharge = dec("1.00")
    else:
        surcharge = dec("0.00")
    return f2(base + surcharge)


# --------------------------------------------------------------------------
# 2. breach score
# --------------------------------------------------------------------------
def in_breach_value(standard, measured_value):
    threshold = dec(standard["threshold_value"])
    value = dec(measured_value)
    if standard["threshold_direction"] == "AT_LEAST":
        return value < threshold
    return value > threshold


def weighted_breach_score(standard, measured_value, breached):
    if not breached:
        return 0.0
    threshold = dec(standard["threshold_value"])
    if threshold == 0:
        return 0.0
    ratio = abs(dec(measured_value) - threshold) / threshold
    if ratio >= dec("0.50"):
        band = dec("1.00")
    elif ratio >= dec("0.25"):
        band = dec("0.60")
    elif ratio >= dec("0.10"):
        band = dec("0.30")
    else:
        band = dec("0.10")
    return f4(dec(standard["criticality_weight"]) * band)


# --------------------------------------------------------------------------
# 3. expense class boundary — PENDING -> REJECT -> LIFE_EVENT -> THRESHOLD -> OPERATING
# --------------------------------------------------------------------------
OPERATING_COST_CEILING_CENTS = 2500000
CAPITAL_REJECT_COST_FLOOR_CENTS = 5000000
CAPITAL_REJECT_CONDITION_SCORE = 60.0


def expense_class(work_order, asset):
    estimated = int(work_order.get("estimated_cost_cents") or 0)
    if estimated == 0 or asset.get("status") not in (
            "BASELINE_ASSESSED", "IN_SERVICE", "REPLACEMENT_FLAGGED"):
        return "PENDING_CLASSIFICATION"
    if estimated >= CAPITAL_REJECT_COST_FLOOR_CENTS and condition_at_least(
            asset.get("condition_score", 0), CAPITAL_REJECT_CONDITION_SCORE):
        return "REJECTED_AS_CAPITAL"
    if estimated >= OPERATING_COST_CEILING_CENTS:
        end_year = int(asset["install_year"]) + int(asset["useful_life_years"])
        if now().year >= end_year:
            return "CAPITAL_LIFE_EVENT"
        return "CAPITAL_THRESHOLD"
    return "OPERATING"


def capital_expense_class(expense):
    return expense in ("CAPITAL_THRESHOLD", "CAPITAL_LIFE_EVENT")


# --------------------------------------------------------------------------
# 4. work order cost variance — round each component, then sum
# --------------------------------------------------------------------------
LOADED_LABOUR_RATE_CENTS = 8450
MATERIALS_OVERHEAD_FACTOR = "1.0875"


def work_order_cost(labour_hours, materials_cents):
    labour_component = icents(dec(labour_hours) * dec(LOADED_LABOUR_RATE_CENTS))
    materials_component = icents(dec(materials_cents) * dec(MATERIALS_OVERHEAD_FACTOR))
    return labour_component + materials_component


# --------------------------------------------------------------------------
# 5. penalty allocation — forward looking share
# --------------------------------------------------------------------------
BREACH_UPLIFT_PCT = "0.15"


def penalty_shares(total_penalty_cents, operator_pct, breach_count):
    total = int(total_penalty_cents)
    base = icents(dec(total) * dec(operator_pct))
    uplift = icents(dec(total) * dec(BREACH_UPLIFT_PCT)) if breach_count >= 1 else 0
    operator = min(base + uplift, total)
    return operator, total - operator


# --------------------------------------------------------------------------
# 6. penalty allocation — chronological comparator basis
# --------------------------------------------------------------------------
REPEAT_TIER_STEP_PCT = "0.15"
REPEAT_TIER_CAP_PCT = "0.40"


def allocation_order(allocation):
    """Allocations under the same permit in ascending creation order."""
    siblings = [a for a in DB["allocations"].values()
                if a["permit_id"] == allocation["permit_id"]]
    siblings.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return siblings


def state_baseline_share(allocation, total_penalty_cents, operator_pct):
    siblings = allocation_order(allocation)
    try:
        n = siblings.index(allocation) + 1
    except ValueError:
        n = 1
    step = min(dec(REPEAT_TIER_STEP_PCT) * (n - 1), dec(REPEAT_TIER_CAP_PCT))
    tier_rate = dec(operator_pct) + step
    share = icents(dec(total_penalty_cents) * tier_rate)
    return min(share, int(total_penalty_cents))


# --------------------------------------------------------------------------
# 7. benchmark comparison
# --------------------------------------------------------------------------
MGD_PER_CAPITA = "0.00011"


def cost_per_million_gallons(contract, municipality):
    daily_mgd = dec(municipality.get("population_served") or 0) * dec(MGD_PER_CAPITA)
    annual_mg = daily_mgd * 365
    if annual_mg == 0:
        return dec(0)
    return dec(contract["annual_fee_cents"]) / annual_mg


LIVE_STATUSES = ("OPERATING", "UNDER_REVIEW", "RENEWED")


def benchmark_index(municipality):
    """Forward-looking index; written to Municipality.benchmark_index_baseline."""
    included = [c for c in DB["contracts"].values()
                if c["municipality_id"] == municipality["id"] and c["status"] in LIVE_STATUSES]
    if not included:
        return 0.0
    total = sum((cost_per_million_gallons(c, municipality) for c in included), dec(0))
    return f4(total / len(included))


def benchmark_comparator(municipality):
    """Chronological comparator basis over every contract of the municipality."""
    contracts = [c for c in DB["contracts"].values()
                 if c["municipality_id"] == municipality["id"]]
    if not contracts:
        return 0.0
    contracts.sort(key=lambda c: (str(c.get("award_date") or ""), c["created_at"], c["_seq"]))
    weight_sum = dec(0)
    acc = dec(0)
    last = len(contracts) - 1
    for idx, contract in enumerate(contracts):
        weight = dec("1.5") if idx == last else dec("1.0")
        acc += weight * cost_per_million_gallons(contract, municipality)
        weight_sum += weight
    if weight_sum == 0:
        return 0.0
    return f4(acc / weight_sum)


def benchmark_ratio(proposed_fee_cents, municipality, contract):
    ratio_base = icents(dec(municipality.get("benchmark_index_baseline") or 0)
                        * dec(contract.get("staffing_floor_fte") or 0) * 12)
    if ratio_base == 0:
        return 0.0
    return f4(dec(proposed_fee_cents) / dec(ratio_base))


# --------------------------------------------------------------------------
# 8. PM compliance rate
# --------------------------------------------------------------------------
PM_GRACE_DAYS = 7
DAY_SECONDS = 86400


def pm_compliance_rate(schedule):
    occurrences = schedule.get("_occurrences") or []
    compliant = 0
    missed = 0
    current = now()
    for occurrence in occurrences:
        due = parse_dt(occurrence["due_at"])
        window_end = due + timedelta(days=PM_GRACE_DAYS)
        work_order = DB["work_orders"].get(occurrence.get("work_order_id"))
        closed_at = parse_dt(work_order.get("status_changed_at")) if work_order else None
        if work_order is not None and work_order.get("status") == "CLOSED" and closed_at is not None \
                and closed_at <= window_end:
            compliant += 1
        elif current > window_end:
            missed += 1
    total = compliant + missed
    if total == 0:
        return 0.0
    return f2(dec(100) * compliant / total)


# --------------------------------------------------------------------------
# 9. notification deadline
# --------------------------------------------------------------------------
CONTAMINATION_NOTIFY_HOURS = 1
OVERFLOW_NOTIFY_HOURS = 2
UPSET_NOTIFY_HOURS = 4
MAIN_BREAK_STANDARD_HOURS = 24
MAIN_BREAK_SEVERE_HOURS = 4
POWER_LOSS_NOTIFY_HOURS = 24


def notification_hours(event_type, severity):
    if event_type == "CONTAMINATION":
        return CONTAMINATION_NOTIFY_HOURS
    if event_type == "SANITARY_OVERFLOW":
        return OVERFLOW_NOTIFY_HOURS
    if event_type == "TREATMENT_UPSET":
        return UPSET_NOTIFY_HOURS
    if event_type == "MAIN_BREAK":
        return MAIN_BREAK_SEVERE_HOURS if severity in ("HIGH", "CRITICAL") else MAIN_BREAK_STANDARD_HOURS
    return POWER_LOSS_NOTIFY_HOURS


def notification_deadline(occurred_at, event_type, severity):
    hours = notification_hours(event_type, severity)
    return occurred_at + timedelta(hours=hours)


def is_notification_late(notified_at, deadline):
    """The boundary is inclusive: filing exactly at the deadline is late."""
    return notified_at >= deadline


# --------------------------------------------------------------------------
# 10. vesting benefit
# --------------------------------------------------------------------------
GRANDFATHERED_YEARS = "20"
ENHANCED_YEARS = "10"
STANDARD_YEARS = "5"
BASIC_YEARS = "1"
BASIC_OFFSET_PER_YEAR_CENTS = 120000
STANDARD_OFFSET_PER_YEAR_CENTS = 185000
ENHANCED_OFFSET_PER_YEAR_CENTS = 250000


def years_of_service(hire_date, contract_start_date):
    span = (contract_start_date - hire_date).total_seconds()
    return rhu(dec(span) / dec(365 * DAY_SECONDS), 2)


def vesting(hire_date, contract_start_date):
    years = years_of_service(hire_date, contract_start_date)
    if years >= dec(GRANDFATHERED_YEARS):
        tier = "GRANDFATHERED"
    elif years >= dec(ENHANCED_YEARS):
        tier = "ENHANCED"
    elif years >= dec(STANDARD_YEARS):
        tier = "STANDARD"
    elif years >= dec(BASIC_YEARS):
        tier = "BASIC"
    else:
        tier = "NONE"
    if tier in ("NONE", "GRANDFATHERED"):
        offset = 0
    elif tier == "ENHANCED":
        offset = icents(dec(ENHANCED_OFFSET_PER_YEAR_CENTS) * years)
    elif tier == "STANDARD":
        offset = icents(dec(STANDARD_OFFSET_PER_YEAR_CENTS) * years)
    else:
        offset = icents(dec(BASIC_OFFSET_PER_YEAR_CENTS) * years)
    return float(years), tier, offset


# --------------------------------------------------------------------------
# 11. transition-back credit (withholding)
# --------------------------------------------------------------------------
WITHHOLDING_CAP_CENTS = 4000000


def outstanding_days(due_at):
    """Whole 24 hour periods elapsed after due_at, floored at zero."""
    delta = (now() - due_at).total_seconds()
    if delta <= 0:
        return 0
    return int(math.floor(delta / DAY_SECONDS))


def withholding_cents(due_at, penalty_per_day_cents, status):
    if status in ("SATISFIED", "WAIVED"):
        return 0
    days = outstanding_days(due_at)
    return min(days * int(penalty_per_day_cents or 0), WITHHOLDING_CAP_CENTS)


# --------------------------------------------------------------------------
# 12. contract settlement net
# --------------------------------------------------------------------------
def operating_days(contract):
    start = parse_dt(contract.get("contract_start_date"))
    if start is None:
        return 0
    delta = (now() - start).total_seconds()
    if delta <= 0:
        return 0
    return int(math.floor(delta / DAY_SECONDS))


def settlement(contract):
    prorated = icents(dec(contract["annual_fee_cents"]) * dec(operating_days(contract)) / dec(365))
    withholding_total = 0
    for obligation in DB["obligations"].values():
        if obligation["contract_id"] == contract["id"]:
            withholding_total += int(obligation.get("withholding_cents") or 0)
    penalty_total = 0
    for allocation in DB["allocations"].values():
        if allocation["contract_id"] == contract["id"] and allocation.get("status") != "VOIDED":
            penalty_total += int(allocation.get("operator_share_cents") or 0)
    return {
        "contract_id": contract["id"],
        "operating_days": operating_days(contract),
        "prorated_fee_cents": prorated,
        "withholding_total_cents": withholding_total,
        "penalty_total_cents": penalty_total,
        "net_payable_cents": prorated - withholding_total - penalty_total,
    }


# --------------------------------------------------------------------------
# helpers used by the workflows
# --------------------------------------------------------------------------
def applicable_response_standard(contract_id):
    """The binding response-time standard under the contract, if any."""
    candidates = [s for s in DB["standards"].values()
                  if s["contract_id"] == contract_id
                  and s["metric_type"] == "RESPONSE_TIME"
                  and s["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (dec(s["threshold_value"]), s["created_at"], s["_seq"]))
    return candidates[0]


def contract_of(rec):
    from core import owner_contract
    cid = owner_contract(rec)
    return DB["contracts"].get(cid) if cid else None
