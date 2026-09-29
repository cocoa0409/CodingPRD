"""The declared calculations, kept free of storage concerns."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

from common import (
    ceil_days,
    date_str,
    parse_date,
    round2,
    round2_frac,
    round_int,
)

HOUR = timedelta(hours=1)


# ---------------------------------------------------------------------------
# input_cutoff_resolution
# ---------------------------------------------------------------------------
def resolve_input_cutoff(pay_date, cutoff_lead_working_days, local_holidays):
    """Walk backwards from pay_date over working days, skipping weekends and
    local holidays. The pay date itself is never counted. Land at 17:00:00.000Z."""
    holidays = set(local_holidays or [])
    counted = 0
    day = pay_date
    guard = 0
    while counted < cutoff_lead_working_days:
        day = day - timedelta(days=1)
        guard += 1
        if guard > 100000:
            break
        if day.weekday() <= 4 and date_str(day) not in holidays:
            counted += 1
    return datetime(day.year, day.month, day.day, 17, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# statutory_due_date
# ---------------------------------------------------------------------------
def statutory_due_at(pay_date, statutory_filing_deadline_days):
    """Calendar-day arithmetic: local holidays play no part here."""
    due = pay_date + timedelta(days=statutory_filing_deadline_days)
    return datetime(due.year, due.month, due.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# input_validation_outcome (stage 1 / stage 2)
# ---------------------------------------------------------------------------
def missing_elements(country_elements, required_keys):
    missing = []
    for key in required_keys:
        value = country_elements.get(key)
        if not isinstance(value, str) or value == "":
            missing.append(key)
    return missing


def record_count_drift_pct(record_count, baseline_employee_count):
    return round2_frac(
        Fraction(abs(record_count - baseline_employee_count), baseline_employee_count) * 100
    )


# ---------------------------------------------------------------------------
# gross_to_net_variance
# ---------------------------------------------------------------------------
DRIFT_LOW = Decimal("3.00")
DRIFT_HIGH = Decimal("10.00")


def compute_variance(run, baseline, country):
    """Returns the four variance fields. Per-employee amounts are exact
    rationals with no intermediate rounding."""
    if baseline is None:
        return {
            "variance_basis": "NO_PRIOR_BASELINE",
            "variance_pct": None,
            "headcount_drift_pct": None,
            "variance_material": False,
        }
    base_count = baseline["employee_count"]
    base_gross = baseline["gross_minor"]
    count = run["employee_count"]
    gross = run["gross_minor"]

    drift = round2_frac(Fraction(abs(count - base_count), base_count) * 100)

    if DRIFT_LOW <= drift <= DRIFT_HIGH:
        basis = "HEADCOUNT_NORMALIZED"
        per_head = Fraction(gross, count)
        base_per_head = Fraction(base_gross, base_count)
        variance = round2_frac((per_head - base_per_head) / base_per_head * 100)
    else:
        basis = "ABSOLUTE_TOTAL"
        variance = round2_frac(Fraction(gross - base_gross, base_gross) * 100)

    gross_delta = abs(gross - base_gross)
    material = bool(
        abs(variance) >= country["materiality_pct"]
        and gross_delta >= country["materiality_floor_minor"]
    )
    return {
        "variance_basis": basis,
        "variance_pct": variance,
        "headcount_drift_pct": drift,
        "variance_material": material,
    }


# ---------------------------------------------------------------------------
# funding_requirement_conversion
# ---------------------------------------------------------------------------
FX_BUFFER_PCT = Decimal("1.50")


def convert_funding(net_minor, employer_cost_minor, provider_fee_minor, fx_rate):
    """Each component is converted and rounded individually before summing."""
    requested_local = net_minor + employer_cost_minor + provider_fee_minor
    components = {
        "net": round_int(Decimal(net_minor) / fx_rate),
        "employer_cost": round_int(Decimal(employer_cost_minor) / fx_rate),
        "provider_fee": round_int(Decimal(provider_fee_minor) / fx_rate),
    }
    subtotal = components["net"] + components["employer_cost"] + components["provider_fee"]
    buffer_minor = round_int(Decimal(subtotal) * FX_BUFFER_PCT / Decimal(100))
    return requested_local, components, subtotal + buffer_minor


def settlement_window(value_date, settlement_window_hours):
    start = datetime(
        value_date.year, value_date.month, value_date.day, 0, 0, 0, 0, tzinfo=timezone.utc
    )
    return start, start + timedelta(hours=settlement_window_hours)


# ---------------------------------------------------------------------------
# filing_penalty_allocation
# ---------------------------------------------------------------------------
STATUTORY_BASE_MINOR = 25000
TIER_ONE_LIMIT = 50000
TIER_TWO_LIMIT = 100000


def late_days_between(due_at, moment):
    return ceil_days(moment - due_at)


def allocate_penalty(late_days, country, provider, responsibility):
    base = STATUTORY_BASE_MINOR + late_days * country["penalty_daily_rate_minor"]
    if base <= TIER_ONE_LIMIT:
        rate = Decimal("0.00")
    elif base <= TIER_TWO_LIMIT:
        rate = Decimal("10.00")
    else:
        rate = Decimal("20.00")
    surcharge = round_int(Decimal(base) * rate / Decimal(100))
    total = base + surcharge
    cap = round_int(Decimal(provider["annual_fee_minor"]) * provider["indemnity_cap_pct"] / Decimal(100))
    headroom = cap - provider["open_penalty_minor"]
    if headroom < 0:
        headroom = 0
    if responsibility == "PROVIDER":
        provider_share = total if total < headroom else headroom
    else:
        provider_share = 0
    client_share = total - provider_share
    if total == 0:
        owner = "NONE"
    elif provider_share == total:
        owner = "PROVIDER"
    elif provider_share == 0:
        owner = "CLIENT"
    else:
        owner = "SHARED"
    return {
        "base_penalty_minor": base,
        "surcharge_minor": surcharge,
        "total_penalty_minor": total,
        "provider_share_minor": provider_share,
        "client_share_minor": client_share,
        "penalty_owner": owner,
    }


# ---------------------------------------------------------------------------
# Period frequency bands
# ---------------------------------------------------------------------------
FREQUENCY_BANDS = {
    "WEEKLY": (7, 7),
    "BIWEEKLY": (14, 14),
    "SEMI_MONTHLY": (14, 17),
    "MONTHLY": (28, 31),
}


def period_days(start_date, end_date):
    return (end_date - start_date).days


def frequency_ok(pay_frequency, days):
    low, high = FREQUENCY_BANDS[pay_frequency]
    return low <= days <= high
