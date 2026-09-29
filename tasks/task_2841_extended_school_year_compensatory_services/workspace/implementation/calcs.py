"""The calculation layer (PRD sections 2.9, 2.10, 3.2, 3.4, 3.7).

All money is integer cents; all service minutes are integers. Divisions are
rounded half up and the rounded value -- never the raw quotient -- feeds the
next step (PRD 2.10).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from errors import ApiError
from store import creation_order, db
from validate import WEEKDAY_BY_INDEX, d

# ------------------------------------------------------------------ constants
REGRESSION_PCT_THRESHOLD = Decimal("25.0")
RECOUPMENT_DAYS_THRESHOLD = 20
MIN_QUALIFYING_DOMAINS = 2
SEVERE_REGRESSION_PCT = Decimal("45.0")
MIN_TRIALS_PER_PROBE = 3
MIN_PROBE_DOMAINS = 2
RECOUPMENT_RATE_PCT_PER_DAY = Decimal("1.2")

MINUTE_ROUNDING_UNIT = 15
ANNUAL_CAP_MINUTES = 3600
MIN_AWARDABLE_MINUTES = 30
SEVERITY_FACTOR_LOW = Decimal("1.00")
SEVERITY_FACTOR_MODERATE = Decimal("1.25")
SEVERITY_FACTOR_SEVERE = Decimal("1.50")
SEVERITY_MODERATE_FLOOR_PCT = Decimal("25.0")
SEVERITY_SEVERE_FLOOR_PCT = Decimal("45.0")
MAX_PROPOSAL_MULTIPLE = Decimal("1.5")

FUND_PRIORITY = ("IDEA_611_FEDERAL", "IDEA_619_FEDERAL", "LOCAL_GENERAL")
INDIRECT_RATE_BY_SOURCE = {
    "IDEA_611_FEDERAL": Decimal("0.08"),
    "IDEA_619_FEDERAL": Decimal("0.08"),
    "LOCAL_GENERAL": Decimal("0.145"),
}
FEDERAL_COMP_CAP_PCT = Decimal("0.25")
FEDERAL_SOURCES = ("IDEA_611_FEDERAL", "IDEA_619_FEDERAL")

MAX_PARENT_NO_SHOWS = 2
DELIVERY_WINDOW_DAYS = 180
DEADLINE_EXTENSION_DAYS = 30
MAX_DISPUTE_ROUNDS = 2
AUTO_AWARD_THRESHOLD_MINUTES = 60
ROUTE_TURNAROUND_MINUTES = 15

SERVICE_TYPE_ROLE_TYPES = {
    "SPECIALIZED_INSTRUCTION": ("SPED_TEACHER", "PARAEDUCATOR"),
    "SPEECH": ("SLP",),
    "OT": ("OT",),
    "PT": ("PT",),
    "COUNSELING": ("COUNSELOR",),
}


# ------------------------------------------------------------------ rounding
def rhu(value, places=0):
    """Round half up to `places` decimals; returns a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def round_half_up_to_multiple(value, unit):
    """floor(x / u + 0.5) * u -- a half remainder rounds up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    steps = (value / Decimal(unit) + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR")
    return int(steps) * unit


def floor_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


# ------------------------------------------------------------------ calendar
def iso_week(day):
    cal = day.isocalendar()
    return (cal[0], cal[1])


def instructional_dates(program):
    """PRD 3.3: the program's instructional-day calendar, ascending."""
    start = d(program["session_start_date"])
    end = d(program["session_end_date"])
    blackout = set(program.get("blackout_dates") or [])
    cancelled = set(program.get("cancelled_dates") or [])
    dates = []
    day = start
    while day <= end:
        stamp = day.isoformat()
        if (WEEKDAY_BY_INDEX[day.weekday()] in program["instructional_weekdays"]
                and stamp not in blackout and stamp not in cancelled):
            dates.append(day)
        day = day + timedelta(days=1)
    return dates


def week_buckets(dates):
    """Group dates into ascending ISO (year, week) buckets."""
    buckets = {}
    for day in dates:
        buckets.setdefault(iso_week(day), []).append(day)
    return [buckets[key] for key in sorted(buckets.keys())]


def derive_program_calendar(program):
    dates = instructional_dates(program)
    program["instructional_days_count"] = len(dates)
    program["instructional_week_count"] = len(week_buckets(dates))
    return dates


def is_instructional_date(program, stamp):
    return any(day.isoformat() == stamp for day in instructional_dates(program))


# ------------------------------------------- regression / recoupment analysis
def regression_pct(probe):
    pre = Decimal(str(probe["pre_break_mastery_pct"]))
    post = Decimal(str(probe["post_break_mastery_pct"]))
    if post >= pre:
        return Decimal("0.0")
    return rhu((pre - post) * Decimal(100) / pre, 1)


def regression_recoupment_analysis(variant, probes):
    """PRD 3.2. Probes are evaluated in pinned array order."""
    regressions = [regression_pct(p) for p in probes]
    max_regression = max(regressions) if regressions else Decimal("0.0")

    days = []
    qualified = 0
    for probe, reg in zip(probes, regressions):
        if variant == "PROBE_BASED":
            day_count = int(probe["recoupment_days_observed"])
            qualifies = (reg >= REGRESSION_PCT_THRESHOLD
                         and day_count >= RECOUPMENT_DAYS_THRESHOLD)
        else:
            day_count = int((reg / RECOUPMENT_RATE_PCT_PER_DAY).to_integral_value(
                rounding=ROUND_CEILING))
            qualifies = (reg > REGRESSION_PCT_THRESHOLD
                         and day_count > RECOUPMENT_DAYS_THRESHOLD)
        days.append(day_count)
        if qualifies:
            qualified += 1

    max_days = max(days) if days else 0

    enough_domains = len(probes) >= MIN_PROBE_DOMAINS
    if variant == "PROBE_BASED":
        sufficient = enough_domains and all(
            int(p["trials_count"]) >= MIN_TRIALS_PER_PROBE for p in probes)
    else:
        sufficient = enough_domains
    sufficiency = "SUFFICIENT" if sufficient else "INSUFFICIENT"

    if sufficiency == "INSUFFICIENT":
        recommendation = "PENDING_DATA"
    elif max_regression >= SEVERE_REGRESSION_PCT:
        recommendation = "ELIGIBLE"
    elif qualified >= MIN_QUALIFYING_DOMAINS:
        recommendation = "ELIGIBLE"
    else:
        recommendation = "INELIGIBLE"

    return {
        "max_regression_pct": float(max_regression),
        "max_recoupment_days": max_days,
        "criteria_met_count": qualified,
        "data_sufficiency": sufficiency,
        "eligibility_recommendation": recommendation,
    }


# ------------------------------------------------- ESY service minutes plan
def esy_service_minutes_plan(program, iep_weekly_minutes):
    """PRD 3.4: four steps, rounding per week before summation."""
    dates = instructional_dates(program)
    if not dates:
        raise ApiError("ERR_NO_INSTRUCTIONAL_DAYS")
    weeks = week_buckets(dates)
    nominal = len(program["instructional_weekdays"])

    per_week = []
    for bucket in weeks:
        per_week.append(rhu_int(
            Decimal(iep_weekly_minutes) * Decimal(len(bucket)) / Decimal(nominal)))
    planned_total = sum(per_week)
    weekly_committed = rhu_int(Decimal(planned_total) / Decimal(len(weeks)))
    daily = rhu_int(Decimal(weekly_committed) / Decimal(nominal))

    max_daily_load = max(
        Decimal(minutes) / Decimal(len(bucket))
        for minutes, bucket in zip(per_week, weeks))
    if max_daily_load > Decimal(program["daily_minutes_cap"]):
        raise ApiError("ERR_DAILY_MINUTES_CAP_EXCEEDED")

    return {
        "planned_total_minutes": planned_total,
        "weekly_minutes_committed": weekly_committed,
        "daily_minutes": daily,
    }


# ---------------------------------------------- compensatory award minutes
def severity_factor_for_student(student_id):
    """PRD 3.7 step 2: the most recent FINALIZED determination of the student."""
    finalized = creation_order([
        det for det in db.determinations.values()
        if det["student_id"] == student_id and det["status"] == "FINALIZED"])
    if not finalized:
        return SEVERITY_FACTOR_LOW
    pct = Decimal(str(finalized[-1]["max_regression_pct"]))
    if pct < SEVERITY_MODERATE_FLOOR_PCT:
        return SEVERITY_FACTOR_LOW
    if pct < SEVERITY_SEVERE_FLOOR_PCT:
        return SEVERITY_FACTOR_MODERATE
    return SEVERITY_FACTOR_SEVERE


def compensatory_award_minutes(student_id, source_program_id, variant):
    """PRD 3.7: four steps. Returns the derived fields without the floor check."""
    matching = []
    for log in db.logs.values():
        commitment = db.commitments.get(log["commitment_id"])
        if commitment is None:
            continue
        if (commitment["student_id"] == student_id
                and commitment["program_id"] == source_program_id):
            matching.append(log)

    eligible = [log for log in matching
                if log["status"] == "VERIFIED"
                and log["outcome"] in ("MISSED_DISTRICT", "PARTIAL")]
    district_missed = sum(
        log["minutes_scheduled"] - log["minutes_delivered"] for log in eligible)

    severity = severity_factor_for_student(student_id)
    if variant == "MINUTE_FOR_MINUTE":
        rounded_raw = int(district_missed)
    else:
        rounded_raw = round_half_up_to_multiple(
            Decimal(district_missed) * severity, MINUTE_ROUNDING_UNIT)

    computed = min(rounded_raw, ANNUAL_CAP_MINUTES)
    return {
        "computed_minutes": computed,
        "severity_factor": float(severity),
        "verified_missed_log_count": len(eligible),
        "excluded_log_count": len(matching) - len(eligible),
    }


def proposal_band(computed_minutes):
    low = computed_minutes
    high = floor_int(Decimal(computed_minutes) * MAX_PROPOSAL_MULTIPLE)
    return low, high


# ------------------------------------------------- fund charge waterfall
def _available(allocation):
    return (allocation["authorized_amount_cents"]
            - allocation["encumbered_amount_cents"]
            - allocation["expended_amount_cents"])


def refresh_available(allocation):
    allocation["available_cents"] = _available(allocation)
    return allocation


def program_allocations_in_priority_order(program_id):
    rows = [a for a in db.allocations.values() if a["program_id"] == program_id]
    return sorted(rows, key=lambda a: (
        FUND_PRIORITY.index(a["fund_source"]), a["created_at"], a["_seq"]))


def fund_charge_waterfall(program_id, rate_cents_per_minute, chargeable_minutes,
                          compensatory=False):
    """PRD 2.9 steps 1-4. Selection is base-cost only and is never retried."""
    base_cost = int(rate_cents_per_minute) * int(chargeable_minutes)

    candidates = [a for a in program_allocations_in_priority_order(program_id)
                  if a["status"] == "OPEN"]
    if not candidates:
        raise ApiError("ERR_FUND_FROZEN")

    selected = None
    for allocation in candidates:
        if _available(allocation) >= base_cost:
            selected = allocation
            break
    if selected is None:
        raise ApiError("ERR_NO_FUND_WITH_CAPACITY")

    indirect = rhu_int(Decimal(base_cost) * INDIRECT_RATE_BY_SOURCE[selected["fund_source"]])
    total = base_cost + indirect

    if total > _available(selected):
        raise ApiError("ERR_FUND_INDIRECT_OVERAGE")

    if compensatory and selected["fund_source"] in FEDERAL_SOURCES:
        ceiling = rhu_int(Decimal(selected["authorized_amount_cents"]) * FEDERAL_COMP_CAP_PCT)
        if selected["compensatory_expended_cents"] + total > ceiling:
            raise ApiError("ERR_SUPPLANT_RESTRICTION")

    return {
        "allocation": selected,
        "base_cost_cents": base_cost,
        "indirect_cost_cents": indirect,
        "total_charge_cents": total,
    }
