"""Domain constants — every value re-derived from PRD.md prose.

Families: logical clock, standard fixture dates, permit fee schedule and
tier bounds, commercial day capacity, cooperative cost share, compliance
points and the suspension threshold, nesting blackout buffer, volunteer
clearance window, habitat priority weights and breeding season, bid ranking,
population objective ratio, pagination defaults. Pure computation helpers
mirror the PRD's pinned formulas so tests can derive expected values.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

__all__ = [
    # clock
    "CLOCK_START_ISO", "CLOCK_START_DATE",
    # standard fixture dates
    "DETERMINATION_COMMENT_OPEN_DATE", "DETERMINATION_COMMENT_CLOSE_DATE",
    "DETERMINATION_POST_CLOSE_DATE", "PERMIT_START_DATE", "PERMIT_END_DATE",
    "CLOSURE_START_DATE", "CLOSURE_END_DATE", "PROGRAM_DATE",
    "TREATMENT_WINDOW_START", "TREATMENT_WINDOW_END",
    "GRAZING_WINDOW_START", "GRAZING_WINDOW_END", "GRAZING_APPLICATION_DEADLINE",
    # permit fees
    "BASE_FEE_CENTS", "PER_DAY_CENTS",
    "TIER_SMALL", "TIER_MEDIUM", "TIER_LARGE",
    "TIER_SMALL_MAX_CREW", "TIER_MEDIUM_MAX_CREW",
    "COMMERCIAL_SURCHARGE_CENTS", "FEE_FLOOR_CENTS", "FEE_CAP_CENTS",
    "MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY",
    # cooperative agreements
    "COOP_SHARE_PCT",
    "INITIAL_COMPLIANCE_POINTS", "SUSPEND_THRESHOLD_POINTS",
    "POINTS_MINOR", "POINTS_MAJOR", "POINTS_CRITICAL", "POINTS_BY_SEVERITY",
    # safety / seasonal
    "NESTING_BUFFER_DAYS", "VOLUNTEER_CLEARANCE_VALID_DAYS",
    # habitat
    "WEIGHT_WATER_MANIPULATION", "WEIGHT_PRESCRIBED_BURN",
    "WEIGHT_INVASIVE_CONTROL", "HABITAT_WEIGHTS",
    "BREEDING_MULTIPLIER", "BREEDING_WINDOW_START_MD", "BREEDING_WINDOW_END_MD",
    # bids
    "RATING_WEIGHT", "MIN_STEWARDSHIP_RATING", "MAX_STEWARDSHIP_RATING",
    # population
    "BELOW_TARGET_RATIO_NUM", "BELOW_TARGET_RATIO_DEN",
    # pagination
    "DEFAULT_LIMIT", "MIN_LIMIT", "MAX_LIMIT", "DEFAULT_OFFSET",
    # pure helpers
    "round_half_up_cents", "parse_date", "format_date", "add_days",
    "clock_iso", "trip_days", "compute_tier_multiplier",
    "compute_provisional_fee_cents", "compute_assessed_fee_cents",
    "compute_period_assessment_cents", "compute_bid_rank_score",
    "is_at_target", "breeding_window_dates", "window_intersects_breeding",
]

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5): startup default before any call is exactly
# 2026-09-01T00:00:00Z and never falls back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START_DATE = "2026-09-01"

# ---------------------------------------------------------------------------
# Standard fixture dates (all consistent with the startup clock; the comment
# window opens after startup and closes before the default permit season).
# ---------------------------------------------------------------------------
DETERMINATION_COMMENT_OPEN_DATE = "2026-09-05"
DETERMINATION_COMMENT_CLOSE_DATE = "2026-09-20"
DETERMINATION_POST_CLOSE_DATE = "2026-09-21"  # first clock date past the window
PERMIT_START_DATE = "2026-10-10"
PERMIT_END_DATE = "2026-10-12"                # 3-day default permit window
CLOSURE_START_DATE = "2026-10-09"
CLOSURE_END_DATE = "2026-10-20"
PROGRAM_DATE = "2026-12-01"
TREATMENT_WINDOW_START = "2026-10-01"
TREATMENT_WINDOW_END = "2026-10-10"
GRAZING_WINDOW_START = "2026-11-01"
GRAZING_WINDOW_END = "2027-02-28"
GRAZING_APPLICATION_DEADLINE = "2026-10-01"

# ---------------------------------------------------------------------------
# Permit fee schedule (PRD §3.3 and §2.8). All monetary values are integer
# cents. Provisional fee = flat base fee only. Assessed fee =
# base + round_half_up(per_day * days * tier) + (surcharge if commercial),
# then capped at FEE_CAP_CENTS, then raised to at least FEE_FLOOR_CENTS.
# ---------------------------------------------------------------------------
BASE_FEE_CENTS = {
    "RESEARCH": 15000,
    "PHOTOGRAPHY": 7500,
    "COMMERCIAL_FILMING": 20000,
    "GUIDED_ACTIVITY": 3000,
}
PER_DAY_CENTS = {
    "RESEARCH": 2000,
    "PHOTOGRAPHY": 1500,
    "COMMERCIAL_FILMING": 5000,
    "GUIDED_ACTIVITY": 800,
}
TIER_SMALL = 1.0          # crew_size <= 9
TIER_MEDIUM = 1.25        # 10 <= crew_size <= 19
TIER_LARGE = 1.5          # crew_size >= 20
TIER_SMALL_MAX_CREW = 9
TIER_MEDIUM_MAX_CREW = 19
COMMERCIAL_SURCHARGE_CENTS = 10000
FEE_FLOOR_CENTS = 5000
FEE_CAP_CENTS = 100000

# Commercial capacity (PRD §3.3): counts COMMERCIAL_FILMING permits only
# (not other use types), in {APPROVED, ACTIVE}, per unit per calendar day.
MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY = 2

# ---------------------------------------------------------------------------
# Cooperative cost share (PRD §3.8): period amount =
# round_half_up(aum_used * rate_cents_per_aum * COOP_SHARE_PCT / 100),
# rounded per period and only then summed.
# ---------------------------------------------------------------------------
COOP_SHARE_PCT = 50

# Compliance points (PRD §3.8): agreements start at 100; a debit leaving the
# agreement below 60 suspends it; exactly 60 remains ACTIVE; a credit
# restoring to >= 60 reinstates a SUSPENDED agreement.
INITIAL_COMPLIANCE_POINTS = 100
SUSPEND_THRESHOLD_POINTS = 60
POINTS_MINOR = 10
POINTS_MAJOR = 25
POINTS_CRITICAL = 50
POINTS_BY_SEVERITY = {
    "MINOR": POINTS_MINOR,
    "MAJOR": POINTS_MAJOR,
    "CRITICAL": POINTS_CRITICAL,
}

# ---------------------------------------------------------------------------
# Seasonal safety policy (PRD §2.11): a PRESCRIBED_BURN must keep a 14-day
# buffer ahead of any NESTING closure (SCHEDULED or ACTIVE) on the unit —
# rejected when burn window_end > closure.start_date - 14 days. A volunteer
# clearance lasts 365 days; the boundary day itself expires.
# ---------------------------------------------------------------------------
NESTING_BUFFER_DAYS = 14
VOLUNTEER_CLEARANCE_VALID_DAYS = 365

# ---------------------------------------------------------------------------
# Habitat priority scoring (PRD §3.1): only COMPLETED treatments contribute.
# Breeding-weighted variant doubles the weight of treatments whose execution
# window intersects March 1 - June 30 of the year of that treatment's
# window_start.
# ---------------------------------------------------------------------------
WEIGHT_WATER_MANIPULATION = 30
WEIGHT_PRESCRIBED_BURN = 50
WEIGHT_INVASIVE_CONTROL = 20
HABITAT_WEIGHTS = {
    "WATER_MANIPULATION": WEIGHT_WATER_MANIPULATION,
    "PRESCRIBED_BURN": WEIGHT_PRESCRIBED_BURN,
    "INVASIVE_CONTROL": WEIGHT_INVASIVE_CONTROL,
}
BREEDING_MULTIPLIER = 2
BREEDING_WINDOW_START_MD = "03-01"
BREEDING_WINDOW_END_MD = "06-30"

# ---------------------------------------------------------------------------
# Bid selection (PRD §3.7): eligible = SUBMITTED bids with
# stewardship_rating >= offering.min_stewardship_rating;
# rank_score = rating * 1000 - rate_cents_per_aum; highest wins;
# ties break toward the earliest created_at.
# ---------------------------------------------------------------------------
RATING_WEIGHT = 1000
MIN_STEWARDSHIP_RATING = 1
MAX_STEWARDSHIP_RATING = 10

# ---------------------------------------------------------------------------
# Population objective (PRD §3.9): AT_TARGET iff survey_count * 10 >=
# target_count * 7 (integer comparison; exactly 70% satisfies).
# ---------------------------------------------------------------------------
BELOW_TARGET_RATIO_NUM = 7
BELOW_TARGET_RATIO_DEN = 10

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3).
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Pure helpers mirroring the PRD's pinned formulas.
# ---------------------------------------------------------------------------
def round_half_up_cents(value) -> int:
    """Round a numeric value to whole cents using round-half-up (PRD §2.8)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_date(date_str: str) -> date:
    """Parse a YYYY-MM-DD domain date."""
    year, month, day = (int(part) for part in date_str.split("-"))
    return date(year, month, day)


def format_date(d: date) -> str:
    """Render a date as YYYY-MM-DD."""
    return d.isoformat()


def add_days(date_str: str, n: int) -> str:
    """Return the date n days after date_str (YYYY-MM-DD in, YYYY-MM-DD out)."""
    return format_date(parse_date(date_str) + timedelta(days=n))


def clock_iso(date_str: str) -> str:
    """Render a YYYY-MM-DD date as a logical-clock instant (midnight UTC)."""
    return f"{date_str}T00:00:00Z"


def trip_days(start_date: str, end_date: str) -> int:
    """Inclusive day count from start_date through end_date (PRD §3.1)."""
    return (parse_date(end_date) - parse_date(start_date)).days + 1


def compute_tier_multiplier(crew_size: int) -> Decimal:
    """Crew tier multiplier: 1.0 for <= 9, 1.25 for 10..19, 1.5 for >= 20."""
    if crew_size <= TIER_SMALL_MAX_CREW:
        return Decimal(str(TIER_SMALL))
    if crew_size <= TIER_MEDIUM_MAX_CREW:
        return Decimal(str(TIER_MEDIUM))
    return Decimal(str(TIER_LARGE))


def compute_provisional_fee_cents(use_type: str) -> int:
    """Provisional estimate: the flat base fee for the use type, nothing more."""
    return BASE_FEE_CENTS[use_type]


def compute_assessed_fee_cents(use_type: str, crew_size: int,
                               start_date: str, end_date: str) -> int:
    """Assessed fee at approve time (PRD §3.3/§2.8).

    base + round_half_up(per_day * days * tier) + commercial surcharge,
    then cap at FEE_CAP_CENTS, then floor at FEE_FLOOR_CENTS.
    """
    days = trip_days(start_date, end_date)
    mult = compute_tier_multiplier(crew_size)
    per_day_product = int(
        (Decimal(PER_DAY_CENTS[use_type]) * days * mult).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    )
    raw = BASE_FEE_CENTS[use_type] + per_day_product
    if use_type == "COMMERCIAL_FILMING":
        raw += COMMERCIAL_SURCHARGE_CENTS
    return max(min(raw, FEE_CAP_CENTS), FEE_FLOOR_CENTS)


def compute_period_assessment_cents(aum_used: int, rate_cents_per_aum: int) -> int:
    """One period's cost share: round_half_up(aum * rate * 50 / 100).

    Rounding happens per period, before summing into the running total.
    """
    product = (Decimal(aum_used) * Decimal(rate_cents_per_aum)
               * Decimal(COOP_SHARE_PCT) / Decimal(100))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_bid_rank_score(stewardship_rating: int, rate_cents_per_aum: int) -> int:
    """rank_score = stewardship_rating * 1000 - rate_cents_per_aum."""
    return stewardship_rating * RATING_WEIGHT - rate_cents_per_aum


def is_at_target(survey_count: int, target_count: int) -> bool:
    """AT_TARGET iff survey_count * 10 >= target_count * 7 (inclusive at 70%)."""
    return survey_count * BELOW_TARGET_RATIO_DEN >= target_count * BELOW_TARGET_RATIO_NUM


def breeding_window_dates(year: int) -> tuple:
    """The breeding window for a year: (YYYY-03-01, YYYY-06-30)."""
    return (f"{year}-{BREEDING_WINDOW_START_MD}", f"{year}-{BREEDING_WINDOW_END_MD}")


def window_intersects_breeding(window_start: str, window_end: str) -> bool:
    """Whether [window_start, window_end] intersects the breeding window of
    window_start's year (PRD §3.1 habitat_priority_breeding rule)."""
    year = parse_date(window_start).year
    bs, be = breeding_window_dates(year)
    return window_start <= be and window_end >= bs
