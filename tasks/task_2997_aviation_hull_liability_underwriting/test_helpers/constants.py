"""Business constants and pure derivation helpers.

Every number here is stated by the PRD.  Money is always an integer count of
cents; rates and factors are always integer parts per million.  Divisions floor
unless the PRD names the operation as one that rounds up.
"""

import math
from datetime import datetime, timezone

from .types import (
    AircraftClass,
    PerilsScope,
    PilotBand,
    LicenseType,
    TerritorialLimit,
    TerritoryCode,
    EndorsementType,
    UseClass,
)

# --------------------------------------------------------------------------
# Scaling
# --------------------------------------------------------------------------
PPM = 1_000_000

# --------------------------------------------------------------------------
# The logical underwriting clock
# --------------------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Register field bounds
# --------------------------------------------------------------------------
LEGAL_NAME_MIN_LEN = 1
LEGAL_NAME_MAX_LEN = 120
HOME_BASE_ICAO_LEN = 4
AOC_NUMBER_MIN_LEN = 4
AOC_NUMBER_MAX_LEN = 16
REGISTRATION_MARK_MIN_LEN = 3
REGISTRATION_MARK_MAX_LEN = 8
MANUFACTURE_YEAR_MIN = 1950
MANUFACTURE_YEAR_MAX = 2026
SEAT_COUNT_MIN = 1
SEAT_COUNT_MAX = 500
PILOT_NAME_MIN_LEN = 1
PILOT_NAME_MAX_LEN = 120
MARKET_NAME_MIN_LEN = 1
MARKET_NAME_MAX_LEN = 80
LOSS_DESCRIPTION_MIN_LEN = 1
LOSS_DESCRIPTION_MAX_LEN = 500
ASSESSOR_REFERENCE_MIN_LEN = 1
ASSESSOR_REFERENCE_MAX_LEN = 80
EXPOSURE_MEMBER_COUNT_MIN = 1
EXPOSURE_MEMBER_COUNT_MAX = 500

# --------------------------------------------------------------------------
# Policy field bounds
# --------------------------------------------------------------------------
BASE_HULL_RATE_PPM_MIN = 1
BASE_HULL_RATE_PPM_MAX = 100_000
HULL_DEDUCTIBLE_PPM_MIN = 0
HULL_DEDUCTIBLE_PPM_MAX = 200_000
ACQUISITION_REPORTING_DAYS_MIN = 1
ACQUISITION_REPORTING_DAYS_MAX = 180
ACQUISITION_REPORTING_DAYS_DEFAULT = 30
POLICY_NUMBER_PREFIX = "AVN-"
POLICY_NUMBER_DIGITS = 6
FIRST_POLICY_NUMBER = "AVN-000001"
DEFAULT_PERMITTED_USE_CLASSES = list(UseClass.ALL)

# --------------------------------------------------------------------------
# Airframe depreciation
# --------------------------------------------------------------------------
RESIDUAL_START_PPM = 1_000_000
ANNUAL_DEPRECIATION_PPM = 40_000
RESIDUAL_FLOOR_PPM = 400_000

# --------------------------------------------------------------------------
# Pilot qualification scoring, out of a maximum of 1000
# --------------------------------------------------------------------------
SCORE_MIN = 0
SCORE_MAX = 1000
HOURS_POINTS_MAX = 400
HOURS_POINTS_DIVISOR = 2000
ON_TYPE_POINTS_MAX = 250
ON_TYPE_POINTS_DIVISOR = 200
INSTRUMENT_RATING_POINTS = 150
LICENCE_POINTS = {
    LicenseType.STUDENT: 0,
    LicenseType.PPL: 80,
    LicenseType.CPL: 150,
    LicenseType.ATPL: 200,
}
RECURRENCY_PENALTY_POINTS = 200
RECURRENCY_GRACE_DAYS = 365

BAND_A_MIN_SCORE = 750
BAND_B_MIN_SCORE = 550
BAND_C_MIN_SCORE = 350

# --------------------------------------------------------------------------
# The four-factor hull rate chain
# --------------------------------------------------------------------------
USE_CLASS_FACTOR_PPM = {
    UseClass.PRIVATE: 1_000_000,
    UseClass.BUSINESS: 1_150_000,
    UseClass.INSTRUCTIONAL: 1_400_000,
    UseClass.COMMERCIAL: 1_750_000,
}
TERRITORY_FACTOR_PPM = {
    TerritorialLimit.DOMESTIC: 1_000_000,
    TerritorialLimit.CONTINENTAL: 1_080_000,
    TerritorialLimit.WORLDWIDE: 1_250_000,
}
BAND_FACTOR_PPM = {
    PilotBand.BAND_A: 900_000,
    PilotBand.BAND_B: 1_000_000,
    PilotBand.BAND_C: 1_250_000,
    PilotBand.BAND_D: 1_600_000,
}
RATE_FLOOR_PPM = 8_000
RATE_CEILING_PPM = 60_000

# --------------------------------------------------------------------------
# Fleet size credit
# --------------------------------------------------------------------------
FLEET_CREDIT_PPM = 50_000
FLEET_CREDIT_MIN_LIVE_SCHEDULES = 5

# --------------------------------------------------------------------------
# Pilot warranty minima by use class
# --------------------------------------------------------------------------
WARRANTY_MIN_TOTAL_HOURS = {
    UseClass.PRIVATE: 100,
    UseClass.BUSINESS: 400,
    UseClass.INSTRUCTIONAL: 500,
    UseClass.COMMERCIAL: 1500,
}
WARRANTY_MIN_ON_TYPE_HOURS = {
    UseClass.PRIVATE: 10,
    UseClass.BUSINESS: 25,
    UseClass.INSTRUCTIONAL: 50,
    UseClass.COMMERCIAL: 100,
}
WARRANTY_INSTRUMENT_REQUIRED_USE_CLASSES = [UseClass.BUSINESS, UseClass.COMMERCIAL]
VERIFIED_HOURS_BREACH_REASON = "VERIFIED_HOURS_BELOW_WARRANTY"

# --------------------------------------------------------------------------
# Over-insurance ceiling
# --------------------------------------------------------------------------
OVER_INSURANCE_CAP_PPM = 1_200_000

# --------------------------------------------------------------------------
# Endorsement pricing
# --------------------------------------------------------------------------
TERRITORY_EXTENSION_ANNUAL_CENTS = {
    TerritoryCode.CONTINENTAL: 180_000,
    TerritoryCode.WORLDWIDE: 420_000,
    TerritoryCode.WAR_ZONE_A: 950_000,
}
PREMISES_LIABILITY_ANNUAL_CENTS = 240_000
PRODUCT_LIABILITY_ANNUAL_CENTS = 360_000
EXPOSURE_RATE_PPM = {
    EndorsementType.NON_OWNED_EXPOSURE: 900,
    EndorsementType.RENTER_EXPOSURE: 1_400,
    EndorsementType.FLYING_CLUB_EXPOSURE: 1_100,
}
REMOVE_AIRCRAFT_RETURN_PPM = 900_000
MAX_QUOTE_ROUNDS = 3

# --------------------------------------------------------------------------
# War, hijacking and terrorism
# --------------------------------------------------------------------------
PERIL_RATE_PPM = {
    PerilsScope.WAR_ONLY: 1_500,
    PerilsScope.WAR_HIJACK: 2_400,
    PerilsScope.WAR_HIJACK_TERRORISM: 3_600,
}
PERILS_SEVERITY_ORDER = [
    PerilsScope.WAR_ONLY,
    PerilsScope.WAR_HIJACK,
    PerilsScope.WAR_HIJACK_TERRORISM,
]

# --------------------------------------------------------------------------
# Fleet declarations
# --------------------------------------------------------------------------
LATE_LOADING_PPM = 150_000

# --------------------------------------------------------------------------
# Claims and settlement
# --------------------------------------------------------------------------
CTL_THRESHOLD_PPM = 750_000
MINIMUM_DEDUCTIBLE_CENTS = 250_000


# --------------------------------------------------------------------------
# Pure derivation helpers
#
# These reproduce the PRD's arithmetic so that tests can assert an
# independently derived expected value rather than echoing the response.
# --------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant, tolerating both a trailing Z and an offset."""
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def calendar_date_of(value: str):
    """The UTC calendar date of an ISO-8601 instant."""
    return parse_instant(value).date()


def whole_days_between(earlier: str, later: str) -> int:
    """Whole days between the UTC calendar dates of two instants."""
    return (calendar_date_of(later) - calendar_date_of(earlier)).days


def calendar_year_of(value: str) -> int:
    """The UTC calendar year of an ISO-8601 instant."""
    return parse_instant(value).year


def floor_ppm(amount: int, factor_ppm: int) -> int:
    """Apply a parts-per-million factor and floor the quotient."""
    return (amount * factor_ppm) // PPM


def ceil_ppm(amount: int, factor_ppm: int) -> int:
    """Apply a parts-per-million factor and round the quotient up."""
    return -((-amount * factor_ppm) // PPM)


def ceil_div(numerator: int, denominator: int) -> int:
    """Integer division rounding up, for the pro-rata families that round up."""
    return -(-numerator // denominator)


def residual_ppm_for_age(age_years: int) -> int:
    """The residual value factor of an airframe of the given whole-year age."""
    age = max(age_years, 0)
    residual = RESIDUAL_START_PPM - age * ANNUAL_DEPRECIATION_PPM
    return max(residual, RESIDUAL_FLOOR_PPM)


def depreciated_value_cents(
    hull_new_value_cents: int, manufacture_year: int, reference_year: int
) -> int:
    """The depreciated hull value of an airframe at a reference calendar year."""
    age = max(reference_year - manufacture_year, 0)
    return floor_ppm(hull_new_value_cents, residual_ppm_for_age(age))


def over_insurance_ceiling_cents(depreciated_cents: int) -> int:
    """The greatest agreed value an airframe of this depreciated value supports."""
    return floor_ppm(depreciated_cents, OVER_INSURANCE_CAP_PPM)


def qualification_score(
    total_logged_hours: int,
    hours_on_type: int,
    instrument_rated: bool,
    license_type: str,
    last_training_completed_at: str,
    clock_utc: str,
) -> int:
    """The pilot qualification score out of 1000, clamped into range."""
    hours_points = min(
        (total_logged_hours * HOURS_POINTS_MAX) // HOURS_POINTS_DIVISOR,
        HOURS_POINTS_MAX,
    )
    type_points = min(
        (hours_on_type * ON_TYPE_POINTS_MAX) // ON_TYPE_POINTS_DIVISOR,
        ON_TYPE_POINTS_MAX,
    )
    rating_points = INSTRUMENT_RATING_POINTS if instrument_rated else 0
    licence_points = LICENCE_POINTS[license_type]
    score = hours_points + type_points + rating_points + licence_points
    if whole_days_between(last_training_completed_at, clock_utc) > RECURRENCY_GRACE_DAYS:
        score -= RECURRENCY_PENALTY_POINTS
    return max(SCORE_MIN, min(SCORE_MAX, score))


def band_for_score(score: int) -> str:
    """The rating band a qualification score falls into, on inclusive floors."""
    if score >= BAND_A_MIN_SCORE:
        return PilotBand.BAND_A
    if score >= BAND_B_MIN_SCORE:
        return PilotBand.BAND_B
    if score >= BAND_C_MIN_SCORE:
        return PilotBand.BAND_C
    return PilotBand.BAND_D


def rate_ppm_for(
    base_hull_rate_ppm: int, use_class: str, territorial_limit_code: str, band: str
) -> int:
    """The hull rate after the four-factor chain, flooring after each step."""
    rate = floor_ppm(base_hull_rate_ppm, USE_CLASS_FACTOR_PPM[use_class])
    rate = floor_ppm(rate, TERRITORY_FACTOR_PPM[territorial_limit_code])
    rate = floor_ppm(rate, BAND_FACTOR_PPM[band])
    return max(RATE_FLOOR_PPM, min(RATE_CEILING_PPM, rate))


def gross_annual_premium_cents(agreed_value_cents: int, rate_ppm: int) -> int:
    """The annual hull premium before any fleet size credit."""
    return floor_ppm(agreed_value_cents, rate_ppm)


def fleet_credit_cents(gross_annual_cents: int) -> int:
    """The five per cent fleet size credit on a gross annual premium."""
    return floor_ppm(gross_annual_cents, FLEET_CREDIT_PPM)


def annual_premium_cents(
    agreed_value_cents: int,
    rate_ppm: int,
    policy_type: str = None,
    live_schedule_count: int = 0,
) -> int:
    """The annual hull premium, applying the fleet credit only when it qualifies."""
    from .types import PolicyType

    gross = gross_annual_premium_cents(agreed_value_cents, rate_ppm)
    if (
        policy_type == PolicyType.FLEET
        and live_schedule_count >= FLEET_CREDIT_MIN_LIVE_SCHEDULES
    ):
        return gross - fleet_credit_cents(gross)
    return gross


def war_premium_cents(
    war_hull_line_cents: int, perils_scope: str, territorial_limit_code: str
) -> int:
    """The war risk premium: floor the peril step, then round the territory step up."""
    base = floor_ppm(war_hull_line_cents, PERIL_RATE_PPM[perils_scope])
    return ceil_ppm(base, TERRITORY_FACTOR_PPM[territorial_limit_code])


def ctl_ratio_ppm(repair_cost_estimate_cents: int, agreed_value_cents: int) -> int:
    """The repair-to-value ratio of a damage assessment, in parts per million."""
    return (repair_cost_estimate_cents * PPM) // agreed_value_cents


def deductible_cents(gross_cents: int, hull_deductible_ppm: int) -> int:
    """The deductible actually applied, subject to the stated monetary floor."""
    return max(floor_ppm(gross_cents, hull_deductible_ppm), MINIMUM_DEDUCTIBLE_CENTS)


def pro_rata_charge_cents(annual_cents: int, unexpired_days: int, term_days: int) -> int:
    """A pro-rata charge, which rounds up."""
    return ceil_div(annual_cents * unexpired_days, term_days)


def pro_rata_return_cents(annual_cents: int, unexpired_days: int, term_days: int) -> int:
    """A pro-rata return of unearned premium, which floors."""
    return (annual_cents * unexpired_days) // term_days


__all__ = [name for name in dir() if not name.startswith("_")]
