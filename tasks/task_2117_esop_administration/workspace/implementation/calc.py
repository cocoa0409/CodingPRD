"""The eleven pinned calculation rules (PRD 2.6 and 3, SCAFFOLD 1.3).

Every ratio is evaluated as exact rational arithmetic (fractions.Fraction) and
rounded exactly once, at the step the rule names.  Rounding half up is used for
the control premium and the marketability-adjusted value; flooring is used
everywhere else.
"""

from datetime import date
from fractions import Fraction

# --------------------------------------------------------------- constants
CONTROL_PREMIUM_OWNERSHIP_THRESHOLD_BPS = 5000
CONTROL_PREMIUM_CAP_CENTS = 1000000000
MIN_SHARE_PRICE_CENTS = 1

GRADED_6YR_TABLE = {0: 0, 1: 0, 2: 20, 3: 40, 4: 60, 5: 80, 6: 100}
DAYS_PER_SERVICE_YEAR = 365

MAX_REALLOCATION_PASSES = 3
MAX_CHALLENGE_ROUNDS = 2
INSTALLMENT_YEARS = 5

QUALIFIED_PERIOD_YEARS = 6
EARLY_YEAR_CAP_PERCENT = 25
FINAL_YEAR_CAP_PERCENT = 50

PUT_WINDOW_DAYS = 60
PUT_WINDOW_COOLING_DAYS = 30

PRIORITY_RANK = {"DEATH": 1, "RETIREMENT_DISABILITY": 2, "TERMINATION": 3, "DIVERSIFICATION": 4}

DEFAULT_HORIZON_YEARS = 5


# ------------------------------------------------------------- arithmetic
def floor_div(numerator, denominator):
    """Exact rational floor."""
    return Fraction(numerator, denominator).__floor__()


def round_half_up(fraction):
    """Nearest whole unit; an exact half goes to the larger unit."""
    if not isinstance(fraction, Fraction):
        fraction = Fraction(fraction)
    whole = fraction.numerator // fraction.denominator
    remainder = fraction - whole
    if remainder >= Fraction(1, 2):
        return whole + 1
    return whole


# ------------------------------------------------------------ date helpers
def iso_to_date(text):
    year, month, day = (int(part) for part in text.split("-"))
    return date(year, month, day)


def days_between(start_iso, end_date):
    return (end_date - iso_to_date(start_iso)).days


def add_years(base, years):
    """Advance a date by whole years; 29 February maps to 28 February."""
    target_year = base.year + years
    month, day = base.month, base.day
    if month == 2 and day == 29:
        try:
            return date(target_year, 2, 29)
        except ValueError:
            return date(target_year, 2, 28)
    return date(target_year, month, day)


def add_days(base, days):
    from datetime import timedelta

    return base + timedelta(days=days)


def whole_year_age(birth_iso, on_date):
    birth = iso_to_date(birth_iso)
    years = on_date.year - birth.year
    if (on_date.month, on_date.day) < (birth.month, birth.day):
        years -= 1
    return years


# ---------------------------------------------------- 1. valuation_share_price
def valuation_share_price(enterprise_value_cents, debt_outstanding_cents,
                          non_operating_assets_cents, control_premium_bps,
                          marketability_discount_bps, total_plan_shares,
                          total_shares_outstanding):
    equity_value_cents = max(
        enterprise_value_cents - debt_outstanding_cents + non_operating_assets_cents, 0)

    ownership_bps = floor_div(total_plan_shares * 10000, total_shares_outstanding)

    if ownership_bps >= CONTROL_PREMIUM_OWNERSHIP_THRESHOLD_BPS:
        uncapped = round_half_up(Fraction(equity_value_cents * control_premium_bps, 10000))
        control_premium_applied_cents = min(uncapped, CONTROL_PREMIUM_CAP_CENTS)
    else:
        control_premium_applied_cents = 0

    # PINNED: premium first on the pre-discount equity value, discount second.
    controlled_value_cents = equity_value_cents + control_premium_applied_cents
    marketable_value_cents = round_half_up(
        Fraction(controlled_value_cents * (10000 - marketability_discount_bps), 10000))

    raw_price_cents = floor_div(marketable_value_cents, total_shares_outstanding)
    share_price_cents = max(raw_price_cents, MIN_SHARE_PRICE_CENTS)

    return {
        "equity_value_cents": equity_value_cents,
        "ownership_bps_at_valuation": ownership_bps,
        "control_premium_applied_cents": control_premium_applied_cents,
        "share_price_cents": share_price_cents,
    }


# ------------------------------------------------------ 2. loan_share_release
def loan_share_release(suspense_shares_before, principal_balance_cents,
                       remaining_interest_cents, principal_cents, interest_cents,
                       release_method):
    principal_balance_after_cents = principal_balance_cents - principal_cents
    remaining_interest_after_cents = remaining_interest_cents - interest_cents

    if principal_balance_after_cents == 0:
        released_shares = suspense_shares_before
    elif release_method == "PRINCIPAL_ONLY":
        numerator = principal_cents
        denominator = principal_cents + principal_balance_after_cents
        released_shares = 0 if denominator == 0 else floor_div(
            suspense_shares_before * numerator, denominator)
    else:  # PRINCIPAL_AND_INTEREST
        numerator = principal_cents + interest_cents
        denominator = (principal_cents + interest_cents
                       + principal_balance_after_cents + remaining_interest_after_cents)
        released_shares = 0 if denominator == 0 else floor_div(
            suspense_shares_before * numerator, denominator)

    return {
        "released_shares": released_shares,
        "suspense_shares_before": suspense_shares_before,
        "suspense_shares_after": suspense_shares_before - released_shares,
        "principal_balance_after_cents": principal_balance_after_cents,
        "remaining_interest_after_cents": remaining_interest_after_cents,
        "fully_repaid": principal_balance_after_cents == 0,
    }


# ---------------------------------------------- 3. participant_vested_percentage
def service_years(hire_date_iso, measurement_date):
    return floor_div(days_between(hire_date_iso, measurement_date), DAYS_PER_SERVICE_YEAR)


def vested_percentage_from_table(years, vesting_schedule):
    if vesting_schedule == "CLIFF_3YR":
        return 0 if years < 3 else 100
    index = years
    if index < 0:
        index = 0
    if index > 6:
        index = 6
    return GRADED_6YR_TABLE[index]


def participant_vesting(hire_date_iso, measurement_date, vesting_schedule,
                        termination_reason=None):
    years = service_years(hire_date_iso, measurement_date)
    percentage = vested_percentage_from_table(years, vesting_schedule)
    if termination_reason in ("RETIREMENT", "DEATH", "DISABILITY"):
        percentage = 100
    return years, percentage


def vested_share_count(allocated_shares, vested_percentage):
    return floor_div(allocated_shares * vested_percentage, 100)


# ------------------------------------------- 4. allocation_pool_distribution
def distribute_pool(pool_shares, open_set):
    """One proportional pass.

    open_set is a list of dicts carrying 'key' (participant id),
    'capped' (capped compensation) and 'order' (created_at ordinal).
    Returns {key: (grant, remainder_awarded)}.
    """
    denominator = sum(member["capped"] for member in open_set)
    result = {}
    if denominator <= 0 or pool_shares <= 0:
        for member in open_set:
            result[member["key"]] = (0, 0)
        return result

    fractions_list = []
    total_floor = 0
    for member in open_set:
        raw = Fraction(pool_shares * member["capped"], denominator)
        floor_value = raw.numerator // raw.denominator
        total_floor += floor_value
        fractions_list.append((member, floor_value, raw - floor_value))

    remainder = pool_shares - total_floor
    # fractional part DESC, capped compensation DESC, created_at ASC
    ranked = sorted(
        fractions_list,
        key=lambda item: (-item[2], -item[0]["capped"], item[0]["order"]),
    )
    winners = set()
    for index in range(min(remainder, len(ranked))):
        winners.add(ranked[index][0]["key"])

    for member, floor_value, _frac in fractions_list:
        extra = 1 if member["key"] in winners else 0
        result[member["key"]] = (floor_value + extra, extra)
    return result


# ------------------------------- 5. annual_additions_cap_reallocation
def run_allocation_passes(pool_shares, eligible, max_shares_cap):
    """eligible: ordered list of dicts with 'key', 'capped', 'order'.

    Returns per-participant statistics plus residue and pass count.
    """
    award = {member["key"]: 0 for member in eligible}
    gross = {member["key"]: 0 for member in eligible}
    remainder_awarded = {member["key"]: 0 for member in eligible}
    open_set = list(eligible)
    pool = pool_shares
    passes_executed = 0

    for current_pass in range(1, MAX_REALLOCATION_PASSES + 1):
        if pool == 0 or not open_set:
            break
        passes_executed = current_pass
        grants = distribute_pool(pool, open_set)
        pool = 0
        for member in open_set:
            key = member["key"]
            grant, extra = grants[key]
            gross[key] += grant
            remainder_awarded[key] += extra
            room = max_shares_cap - award[key]
            if room < 0:
                room = 0
            taken = grant if grant < room else room
            award[key] += taken
            pool += grant - taken
        open_set = [m for m in open_set if award[m["key"]] < max_shares_cap]

    return {
        "award": award,
        "gross": gross,
        "remainder_awarded": remainder_awarded,
        "residual_shares": pool,
        "passes_executed": passes_executed,
    }


# ---------------------------------------------- 6. installment_schedule_build
def installment_plan(approved_shares, installment_count, commenced_at_date):
    base_shares = floor_div(approved_shares, installment_count)
    remainder = approved_shares - base_shares * installment_count
    rows = []
    for k in range(1, installment_count + 1):
        shares = base_shares + (remainder if k == installment_count else 0)
        rows.append({
            "sequence_number": k,
            "shares_scheduled": shares,
            "scheduled_date": add_years(commenced_at_date, k - 1).isoformat(),
        })
    return rows


# ------------------------------- 7. diversification_eligibility_window
def diversification_anchor_year(date_of_birth_iso, hire_date_iso, min_age, min_years):
    return max(iso_to_date(date_of_birth_iso).year + min_age,
               iso_to_date(hire_date_iso).year + min_years)


def diversification_year_index(plan_year, anchor_year):
    return plan_year - anchor_year + 1


def diversification_cap_percent(year_index):
    return (FINAL_YEAR_CAP_PERCENT if year_index == QUALIFIED_PERIOD_YEARS
            else EARLY_YEAR_CAP_PERCENT)


def diversification_available_shares(allocated_shares, diversified_cumulative, cap_percent):
    base = allocated_shares + diversified_cumulative
    cumulative_cap = floor_div(base * cap_percent, 100)
    return cumulative_cap - diversified_cumulative


# ------------------------------------------- 8. put_window_cooling_buffer
def put_window_candidate(payment_date):
    close_date = add_days(payment_date, PUT_WINDOW_DAYS - 1)
    return payment_date, close_date


def put_window_buffer_ok(candidate_open, last_close_iso):
    if not last_close_iso:
        return True
    earliest = add_days(iso_to_date(last_close_iso), PUT_WINDOW_COOLING_DAYS)
    return not (candidate_open < earliest)


# -------------------------------------------- 10. statement_snapshot pieces
def vested_value_cents(closing_shares, vested_percentage, share_price_cents):
    return floor_div(closing_shares * vested_percentage, 100) * share_price_cents


# ------------------------------------- 11. repurchase_obligation_forecast
def coverage_bps(reserve_cents, projected_obligation_cents):
    if projected_obligation_cents == 0:
        return 10000
    return floor_div(reserve_cents * 10000, projected_obligation_cents)
