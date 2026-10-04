"""Domain constants — numeric values pinned by the PRD, plus the small
pure calculators that derive expected values from them.

Every monetary value is an integer number of cents; every eligibility or
activity quantity is an integer MHz-pop unit. Ratio comparisons are done by
integer cross-multiplication; round_half_up is the only rounding mode.

Also carries the canonical clock instants shared by the fixture chains. The
logical clock starts at CLOCK_EPOCH_ISO and every future instant a fixture
needs is reached by advancing the clock — never by wall-clock reads.
"""
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# API mounting
# ---------------------------------------------------------------------------

API_PREFIX = "/spectrum-auctions"
# The clock endpoint is deliberately mounted OUTSIDE the prefix.
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_EPOCH_ISO = "2026-09-01T00:00:00Z"
# Canonical fixture instants (all >= epoch, all reached via the clock endpoint).
DEFAULT_APPLICATION_DEADLINE_ISO = "2026-09-15T00:00:00Z"
QUIET_PERIOD_DAY_ISO = "2026-09-16T00:00:00Z"   # first instant >= deadline
GRANT_DAY_ISO = "2026-10-01T00:00:00Z"
SECOND_GRANT_DAY_ISO = "2026-10-02T00:00:00Z"
# Canonical incumbent relocation window (must be > GRANT_DAY when combined).
TRANSITION_WINDOW_START_ISO = "2026-10-05T00:00:00Z"
TRANSITION_WINDOW_END_ISO = "2026-11-05T00:00:00Z"


def iso_after_days(base_iso: str, days: int) -> str:
    """Add `days` 24-hour multiples to an ISO 8601 UTC instant.

    Day arithmetic on the logical clock is calendar-naive: a day is a
    24-hour multiple, so this is plain timedelta addition. Renders back in
    the same 'YYYY-MM-DDTHH:MM:SSZ' form the clock reads.
    """
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    result = base + timedelta(days=days)
    result = result.astimezone(timezone.utc)
    return result.strftime("%Y-%m-%dT%H:%M:%SZ")


def days_between(start_iso: str, end_iso: str) -> int:
    """Whole 24-hour multiples between two ISO 8601 UTC instants (floor)."""
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    return (end - start).days


# ---------------------------------------------------------------------------
# Bidding eligibility (PRD: one eligibility unit per 2500 cents held)
# ---------------------------------------------------------------------------

UPFRONT_CENTS_PER_ELIGIBILITY_UNIT = 2500


def eligibility_units_for(upfront_held_cents: int) -> int:
    """floor(held / 2500) — the live bidding-eligibility rule."""
    return upfront_held_cents // UPFRONT_CENTS_PER_ELIGIBILITY_UNIT


# ---------------------------------------------------------------------------
# Bidding credits (tier boundaries are INCLUSIVE: <= qualifies)
# ---------------------------------------------------------------------------

ATTRIBUTABLE_STAKE_PCT = 25           # attribution requires stake STRICTLY > 25
SMALL_BIZ_TIER1_MAX_REVENUE_CENTS = 400_000_000
SMALL_BIZ_TIER1_CREDIT_PCT = 35
SMALL_BIZ_TIER2_MAX_REVENUE_CENTS = 2_000_000_000
SMALL_BIZ_TIER2_CREDIT_PCT = 25
SMALL_BIZ_TIER3_MAX_REVENUE_CENTS = 5_500_000_000
SMALL_BIZ_TIER3_CREDIT_PCT = 15
RURAL_SERVICE_POPULATION_CAP = 250_000
RURAL_CREDIT_PCT = 15


def expected_attributable_revenue_cents(
    own_annual_revenue_cents: int, ownership_interests: list
) -> int:
    """own revenue plus holder revenues for stakes STRICTLY greater than 25%."""
    total = own_annual_revenue_cents
    for oi in ownership_interests or []:
        if oi["stake_pct"] > ATTRIBUTABLE_STAKE_PCT:
            total += oi["holder_annual_revenue_cents"]
    return total


def expected_credit_pct(
    claims_small_business: bool,
    claims_rural_credit: bool,
    attributable_revenue_cents: int,
    service_population: int,
) -> int:
    """Tiered credit assignment evaluated at qualification."""
    if claims_small_business:
        if attributable_revenue_cents <= SMALL_BIZ_TIER1_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER1_CREDIT_PCT
        if attributable_revenue_cents <= SMALL_BIZ_TIER2_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER2_CREDIT_PCT
        if attributable_revenue_cents <= SMALL_BIZ_TIER3_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER3_CREDIT_PCT
        return 0
    if claims_rural_credit:
        return (
            RURAL_CREDIT_PCT
            if service_population <= RURAL_SERVICE_POPULATION_CAP
            else 0
        )
    return 0


# ---------------------------------------------------------------------------
# Product arithmetic (exact integer; no rounding)
# ---------------------------------------------------------------------------

def bidding_units(mhz_size: int, population: int) -> int:
    return mhz_size * population


def opening_price_cents(mhz_size: int, population: int, price_per_mhz_pop_cents: int) -> int:
    return mhz_size * population * price_per_mhz_pop_cents


# ---------------------------------------------------------------------------
# Clock price increments (tiered; cross-multiplied; boundaries inclusive on
# the lower side; a product below its own supply closes)
# ---------------------------------------------------------------------------

CLOCK_INCREMENT_TIER1_RATIO_NUM = 3
CLOCK_INCREMENT_TIER1_RATIO_DEN = 2
CLOCK_INCREMENT_TIER1_PCT = 15
CLOCK_INCREMENT_TIER2_RATIO_NUM = 6
CLOCK_INCREMENT_TIER2_RATIO_DEN = 5
CLOCK_INCREMENT_TIER2_PCT = 10
CLOCK_INCREMENT_TIER3_RATIO_NUM = 1
CLOCK_INCREMENT_TIER3_RATIO_DEN = 1
CLOCK_INCREMENT_TIER3_PCT = 5


def round_half_up(numerator: int, denominator: int = 1) -> int:
    """round_half_up(numerator / denominator) to an integer.

    The system's only rounding mode: halves round away from zero. All inputs
    here are non-negative integers, so floor((2n + d) / (2d)) is exact.
    """
    return (2 * numerator + denominator) // (2 * denominator)


def expected_increment_pct(demand_quantity: int, supply_per_area: int):
    """Increment percentage for a product, or None when it closes."""
    d, s = demand_quantity, supply_per_area
    if d * CLOCK_INCREMENT_TIER1_RATIO_DEN >= CLOCK_INCREMENT_TIER1_RATIO_NUM * s:
        return CLOCK_INCREMENT_TIER1_PCT
    if d * CLOCK_INCREMENT_TIER2_RATIO_DEN >= CLOCK_INCREMENT_TIER2_RATIO_NUM * s:
        return CLOCK_INCREMENT_TIER2_PCT
    if d * CLOCK_INCREMENT_TIER3_RATIO_DEN >= CLOCK_INCREMENT_TIER3_RATIO_NUM * s:
        return CLOCK_INCREMENT_TIER3_PCT
    return None  # product closes


def expected_next_price_cents(last_price_cents: int, demand_quantity: int, supply_per_area: int):
    """round_half_up(last * (100 + pct) / 100), or None when the product closes."""
    pct = expected_increment_pct(demand_quantity, supply_per_area)
    if pct is None:
        return None
    return round_half_up(last_price_cents * (100 + pct), 100)


# ---------------------------------------------------------------------------
# Activity requirement (stage 1 below STAGE2_START_ROUND, else stage 2)
# ---------------------------------------------------------------------------

STAGE1_ACTIVITY_MILLI = 800
STAGE2_ACTIVITY_MILLI = 950
STAGE2_START_ROUND = 4


def expected_stage(round_number: int) -> int:
    return 1 if round_number < STAGE2_START_ROUND else 2


def required_activity_milli(round_number: int) -> int:
    return STAGE1_ACTIVITY_MILLI if expected_stage(round_number) == 1 else STAGE2_ACTIVITY_MILLI


def expected_eligibility_after_close(
    activity_units: int, eligibility_units: int, round_number: int
) -> int:
    """Activity rule at round close. Boundary is INCLUSIVE: meeting the
    requirement leaves eligibility unchanged; missing it floors
    activity * 1000 / required_milli."""
    required_milli = required_activity_milli(round_number)
    if activity_units * 1000 >= required_milli * eligibility_units:
        return eligibility_units
    return (activity_units * 1000) // required_milli


# ---------------------------------------------------------------------------
# Settlement pricing (per-license round_half_up FIRST, then sum)
# ---------------------------------------------------------------------------

def expected_provisional_net_price_cents(gross_clock_price_cents: int, credit_pct: int) -> int:
    return round_half_up(gross_clock_price_cents * (100 - credit_pct), 100)


def expected_net_price_cents(gross_clock_price_cents: int, assignment_bid_cents: int, credit_pct: int) -> int:
    return round_half_up((gross_clock_price_cents + assignment_bid_cents) * (100 - credit_pct), 100)


def expected_credit_amount_cents(gross_clock_price_cents: int, assignment_bid_cents: int, credit_pct: int) -> int:
    gross_final = gross_clock_price_cents + assignment_bid_cents
    return gross_final - expected_net_price_cents(gross_clock_price_cents, assignment_bid_cents, credit_pct)


# ---------------------------------------------------------------------------
# License lifecycle windows (day arithmetic on the logical clock)
# ---------------------------------------------------------------------------

PAYMENT_DEADLINE_DAYS = 30
LICENSE_TERM_DAYS = 3650
RENEWAL_WINDOW_DAYS = 365
RENEWAL_EXTENSION_DAYS = 3650
INCUMBENT_TRANSITION_BUFFER_DAYS = 30


def expected_payment_deadline(created_at_iso: str) -> str:
    return iso_after_days(created_at_iso, PAYMENT_DEADLINE_DAYS)


def expected_term_end(grant_date_iso: str, renewals_granted: int = 0) -> str:
    return iso_after_days(
        grant_date_iso, LICENSE_TERM_DAYS + renewals_granted * RENEWAL_EXTENSION_DAYS
    )


def renewal_window_start(term_end_iso: str) -> str:
    return iso_after_days(term_end_iso, -RENEWAL_WINDOW_DAYS)


# ---------------------------------------------------------------------------
# Buildout milestones
# ---------------------------------------------------------------------------

INTERIM_MILESTONE_DAYS = 1095
INTERIM_COVERAGE_PCT = 40
FINAL_MILESTONE_DAYS = 2190
FINAL_COVERAGE_PCT = 70
INTERIM_MISS_ACCELERATION_DAYS = 365


def expected_milestone_due_date(grant_date_iso: str, milestone_type: str) -> str:
    days = INTERIM_MILESTONE_DAYS if milestone_type == "INTERIM" else FINAL_MILESTONE_DAYS
    return iso_after_days(grant_date_iso, days)


def coverage_acceptable(covered_population: int, required_coverage_pct: int, area_population: int) -> bool:
    """Integer cross-multiplication with an INCLUSIVE boundary."""
    return covered_population * 100 >= required_coverage_pct * area_population


# ---------------------------------------------------------------------------
# Unjust enrichment (five 365-day years; 100/80/60/40/20 then 0)
# ---------------------------------------------------------------------------

UNJUST_ENRICHMENT_DAYS_PER_YEAR = 365
UNJUST_ENRICHMENT_PERIOD_YEARS = 5
UNJUST_ENRICHMENT_SCHEDULE = {0: 100, 1: 80, 2: 60, 3: 40, 4: 20, 5: 0}


def expected_unjust_enrichment_cents(
    credit_amount_cents: int,
    grant_date_iso: str,
    filing_instant_iso: str,
    transferee_credit_pct: int,
    license_credit_pct: int,
) -> int:
    """Repayment computed at transfer filing from the logical clock."""
    if credit_amount_cents == 0:
        return 0
    years_elapsed = days_between(grant_date_iso, filing_instant_iso) // UNJUST_ENRICHMENT_DAYS_PER_YEAR
    if transferee_credit_pct < license_credit_pct:
        schedule_pct = 100
    else:
        schedule_pct = UNJUST_ENRICHMENT_SCHEDULE[min(years_elapsed, UNJUST_ENRICHMENT_PERIOD_YEARS)]
    return round_half_up(credit_amount_cents * schedule_pct, 100)


# ---------------------------------------------------------------------------
# Relocation cost shares (floor + largest remainder; ties by created_at ASC)
# ---------------------------------------------------------------------------

def expected_relocation_shares_proportional(relocation_cost_cents: int, licenses_with_units: list) -> dict:
    """BINDING variant: share by bidding units. `licenses_with_units` is a list
    of (license_id, units, created_at_iso). Remainder cents go one at a time to
    licenses ordered units DESC, tie-break created_at ASC. Returns
    {license_id: amount_cents}."""
    if not licenses_with_units:
        return {}
    total_units = sum(u for _, u, _ in licenses_with_units)
    base = {lid: (relocation_cost_cents * u) // total_units for lid, u, _ in licenses_with_units}
    remainder = relocation_cost_cents - sum(base.values())
    order = sorted(licenses_with_units, key=lambda t: (-t[1], t[2]))
    for i in range(remainder):
        base[order[i % len(order)][0]] += 1
    return base


def expected_relocation_shares_equal(relocation_cost_cents: int, licenses_with_units: list) -> dict:
    """DISPUTE-REFERENCE variant: equal split, same remainder rule."""
    if not licenses_with_units:
        return {}
    n = len(licenses_with_units)
    base = {lid: relocation_cost_cents // n for lid, _, _ in licenses_with_units}
    remainder = relocation_cost_cents - sum(base.values())
    order = sorted(licenses_with_units, key=lambda t: (-t[1], t[2]))
    for i in range(remainder):
        base[order[i % len(order)][0]] += 1
    return base
