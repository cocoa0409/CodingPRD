"""The declared calculations (PRD sections 2.8, 3.1, 3.3, 3.4, 3.6, 3.7, 3.8, 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

import clock

COMMISSION_CENTS_PER_SHARE = 25
BPS_SCALE = 10000

PTEP_DAYS = {
    "FOR_CAUSE": 0,
    "VOLUNTARY": 90,
    "INVOLUNTARY": 180,
    "RETIREMENT": 1095,
    "DEATH": 365,
}


def div_half_up(numerator, denominator):
    """Exact integer division rounded half up (ties away from zero)."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def div_floor(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


def ceil_div(numerator, denominator):
    if denominator <= 0:
        return 0
    if numerator <= 0:
        return 0
    return -(-numerator // denominator)


def ratio_6dp(actual, target):
    """round_half_up(actual / target, 6) evaluated in exact decimal arithmetic."""
    target_dec = Decimal(str(target))
    if target_dec == 0:
        return Decimal(0)
    value = Decimal(str(actual)) / target_dec
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# --- plan reserve ledger -----------------------------------------------------

def available_reserve(total_authorized, committed, returned):
    return total_authorized - committed + returned


def reserve_posture(available, low_reserve_threshold_bps, total_authorized):
    """Exact integer cross-multiplication; exactly on the threshold is OPEN."""
    if available * BPS_SCALE >= low_reserve_threshold_bps * total_authorized:
        return "OPEN"
    return "RESTRICTED"


def gross_burn_rate_bps(fiscal_gross, common_outstanding):
    return div_half_up(fiscal_gross * BPS_SCALE, common_outstanding)


def net_burn_rate_bps(fiscal_gross, fiscal_returned, common_outstanding):
    value = div_half_up((fiscal_gross - fiscal_returned) * BPS_SCALE, common_outstanding)
    return max(0, value)


def headroom_shares(burn_rate_limit_bps, common_outstanding, fiscal_gross):
    allowance = div_floor(burn_rate_limit_bps * common_outstanding, BPS_SCALE)
    return max(0, allowance - fiscal_gross)


def evergreen_topup(common_outstanding, evergreen_pct_bps, evergreen_cap_shares):
    """Round first, then apply the cap."""
    raw = div_half_up(common_outstanding * evergreen_pct_bps, BPS_SCALE)
    return min(raw, evergreen_cap_shares)


# --- grant weighting ---------------------------------------------------------

COMMITTED_TRANCHE_STATUSES = ("UNVESTED", "VESTED", "SETTLED")
OUTSTANDING_TRANCHE_STATUSES = ("UNVESTED", "VESTED")


def committed_shares(tranche_rows):
    return sum(t["shares"] for t in tranche_rows if t["status"] in COMMITTED_TRANCHE_STATUSES)


def fungible_weighted_shares(award_type, committed, fungible_ratio_full_value_bps):
    if award_type in ("RSU", "PSU"):
        return div_half_up(committed * fungible_ratio_full_value_bps, BPS_SCALE)
    return committed


def outstanding_shares(tranche_rows):
    return sum(t["shares"] for t in tranche_rows if t["status"] in OUTSTANDING_TRANCHE_STATUSES)


# --- performance certification ----------------------------------------------

def payout_multiplier_bps(actual_value, target_value):
    ratio = ratio_6dp(actual_value, target_value)
    if ratio < Decimal("0.800000"):
        return 0
    if ratio < Decimal("0.900000"):
        return 5000
    if ratio < Decimal("1.000000"):
        return 7500
    if ratio < Decimal("1.100000"):
        return 10000
    if ratio < Decimal("1.200000"):
        return 15000
    return 20000


def performance_tranche_shares(target_shares, multiplier_bps):
    return div_half_up(target_shares * multiplier_bps, BPS_SCALE)


# --- participant derived figures --------------------------------------------

def age_and_service(birth_date, hire_date, reference_date):
    age = clock.whole_years_between(birth_date, reference_date)
    service = clock.whole_years_between(hire_date, reference_date)
    return age, service


def retirement_eligible(age_years, service_years):
    return age_years >= 55 and (age_years + service_years) >= 65


def ptep_expiry(termination_date, termination_reason):
    return clock.add_days(termination_date, PTEP_DAYS[termination_reason])


# --- mobility sourcing and tax allocation -----------------------------------

def contributing_assignments(rows, period_start, period_end):
    """Only periods fully contained in the sourcing window contribute."""
    out = []
    for row in rows:
        start = clock.parse_date(row["start_date"])
        end_raw = row.get("end_date")
        if end_raw is None:
            continue
        end = clock.parse_date(end_raw)
        if start >= period_start and end <= period_end:
            out.append(row)
    return out


def group_by_jurisdiction(rows):
    """jurisdiction_code -> (summed workdays, max tax_rate_bps)."""
    groups = {}
    for row in rows:
        code = row["jurisdiction_code"]
        workdays, rate = groups.get(code, (0, 0))
        groups[code] = (workdays + row["workdays"], max(rate, row["tax_rate_bps"]))
    return groups


def allocate_bps(groups):
    """Largest-remainder waterfall over 10000 bps; returns code -> allocation_bps."""
    total = sum(workdays for workdays, _ in groups.values())
    if total <= 0:
        return {}, 0
    floors = {}
    remainders = {}
    for code, (workdays, _rate) in groups.items():
        scaled = workdays * BPS_SCALE
        floor_value = scaled // total
        floors[code] = floor_value
        remainders[code] = scaled - floor_value * total
    leftover = BPS_SCALE - sum(floors.values())
    order = sorted(groups.keys(), key=lambda code: (-remainders[code], code))
    for code in order[:max(0, leftover)]:
        floors[code] += 1
    return floors, total


def tax_amount_cents(taxable_income_cents, allocation_bps, tax_rate_bps):
    return div_half_up(taxable_income_cents * allocation_bps * tax_rate_bps, 100000000)


def blended_rate_bps(total_tax_cents, taxable_income_cents):
    if taxable_income_cents == 0:
        return 0
    return div_half_up(total_tax_cents * BPS_SCALE, taxable_income_cents)


# --- settlement withholding mechanics ---------------------------------------

def withholding(method, gross_shares, fmv_per_share_cents, total_tax_cents):
    """Returns (shares_withheld, shares_sold, net_shares, residual_cash, cash_due)."""
    if method == "SHARE_WITHHOLD":
        withheld = ceil_div(total_tax_cents, fmv_per_share_cents)
        residual = withheld * fmv_per_share_cents - total_tax_cents
        return withheld, 0, gross_shares - withheld, residual, 0
    if method == "SELL_TO_COVER":
        net_proceeds_per_share = fmv_per_share_cents - COMMISSION_CENTS_PER_SHARE
        sold = ceil_div(total_tax_cents, net_proceeds_per_share)
        gross_proceeds = sold * net_proceeds_per_share
        residual = gross_proceeds - total_tax_cents
        return 0, sold, gross_shares - sold, residual, 0
    # CASH_REMITTANCE
    return 0, 0, gross_shares, 0, total_tax_cents


# --- section 16 filing deadline ---------------------------------------------

def report_due_at(transaction_at):
    day = transaction_at.astimezone(clock.timezone.utc).date() \
        if hasattr(transaction_at, "astimezone") else transaction_at
    if not clock.is_business_day(day):
        day = clock.next_business_day(day)
    day = clock.advance_business_days(day, 2)
    return clock.end_of_day(day)


# --- rule 10b5-1 cooling-off ------------------------------------------------

def cooling_off_days(insider_status, adopted_at, next_earnings_release_at):
    if insider_status == "NON_INSIDER":
        return 0
    if insider_status == "DESIGNATED_INSIDER":
        return 30
    # SECTION_16_OFFICER
    if next_earnings_release_at is None:
        return 90
    target = clock.advance_business_days(next_earnings_release_at.date(), 2)
    candidate = (target - adopted_at.date()).days
    return max(90, min(120, candidate))
