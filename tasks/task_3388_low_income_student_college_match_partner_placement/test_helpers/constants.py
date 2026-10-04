"""Domain thresholds and calculation mirrors.

Every numeric constant below is pinned to a verbatim figure in PRD.md
(integer cents where the PRD spells the value with thousand separators).
The pure helper functions mirror the PRD's published formulas so tests can
compute expected values without re-deriving the arithmetic inline.
"""
import math
from decimal import ROUND_HALF_UP, Decimal

# --- Logical clock (PRD: before being set, the clock reads exactly this) ---
LOGICAL_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# --- Canonical "Cycle A" windows used across the fixtures ------------------
# Application window opens exactly at the logical-clock default (both window
# bounds are inclusive per the PRD), so the default clock is inside it.
CYCLE_A_APP_OPENS_AT = "2026-09-01T00:00:00Z"
CYCLE_A_APP_CLOSES_AT = "2026-09-30T23:59:59Z"
CYCLE_A_RANKING_OPENS_AT = "2026-10-15T00:00:00Z"
CYCLE_A_RANKING_CLOSES_AT = "2026-10-31T23:59:59Z"

# Clock positions fixtures move to:
#  - inside the ranking window
CLOCK_IN_RANKING_WINDOW = "2026-10-16T00:00:00Z"
#  - past ranking_closes_at (unlocks the RANKING -> MATCH_RUN advance)
CLOCK_AFTER_RANKING_WINDOW = "2026-11-01T00:00:00Z"
#  - further past the window (used by tests that need both a state and a
#    temporal violation to coexist)
CLOCK_PAST_ALL_WINDOWS = "2026-11-05T00:00:00Z"

# --- Pagination (PRD: limit defaults to 10, min 1, max 100; offset 0) ------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Household income cap (PRD: $65,000 for a household of four, +/- $4,000
#     per member above or below four; income exactly at the cap is eligible) -
BASE_CAP_CENTS = 6_500_000
REF_HOUSEHOLD_SIZE = 4
PER_MEMBER_ADJUST_CENTS = 400_000

# --- Academic eligibility screen (PRD: standard path gpa >= 350 and
#     test >= 1200; prep-alumni waiver path gpa >= 330, test waived) --------
MIN_GPA_SCALED = 350
MIN_TEST_SCORE = 1200
PREP_WAIVER_MIN_GPA = 330

# --- Academic index (PRD: twice gpa_scaled plus floor(test/4), test null
#     counts 0, capped at 2,000) -------------------------------------------
AI_CAP = 2000
AI_GPA_WEIGHT = 2
AI_TEST_DIVISOR = 4

# --- Need tier (PRD: cap halved, half rounded half-up; income at or below
#     the half yields HIGH) --------------------------------------------------
NEED_HIGH_FRACTION = 0.5

# --- Expected family contribution, PROVISIONAL variant (PRD: allowance
#     $24,000 + $6,000 per member; rate 0.20; floored at zero) --------------
P_ALLOW_BASE_CENTS = 2_400_000
P_ALLOW_PER_MEMBER_CENTS = 600_000
P_RATE = 0.20

# --- Expected family contribution, VERIFIED variant (PRD: 12% asset
#     add-back rounded half-up BEFORE the rate multiplication; allowance
#     $20,000 + $5,500 per verified member; rate 0.22; floored at zero) -----
V_ASSET_RATE = 0.12
V_ALLOW_BASE_CENTS = 2_000_000
V_ALLOW_PER_MEMBER_CENTS = 550_000
V_RATE = 0.22

# --- Aid package composition (PRD: work-study lesser of $3,000 cap and 10%
#     of need; loan zero at NO_LOAN else lesser of $1,500 cap and 20% of
#     need after work-study; grant is the unrounded remainder) --------------
WORK_STUDY_CAP_CENTS = 300_000
WORK_STUDY_RATE = 0.10
LOAN_CAP_CENTS = 150_000
LOAN_RATE = 0.20

# --- Regular-pool priority score (PRD: +40 prep alum, +25 converted
#     referral, +15 need-aware when the viewing college is NO_LOAN and the
#     application need_tier is HIGH) ----------------------------------------
PREP_ALUM_BONUS = 40
REFERRAL_BONUS = 25
NEED_AWARE_BONUS = 15

# --- Ranking list shape (PRD: at least 1 and at most 12 entries) -----------
MAX_RANKS = 12

# --- Discrepancy assessment (PRD: strictly greater than ten percent of the
#     reported figure is DISCREPANCY; exactly ten percent is VERIFIED) ------
DISCREPANCY_MAX_PCT = 10

# --- Persistence rates (PRD: basis points, numerator * 10,000 / denominator,
#     rounded half-up; empty denominator reports 0) --------------------------
RATE_SCALE_BP = 10_000

# --- A well-formed UUID that names no resource (used by not-found and
#     referential-integrity tests) -------------------------------------------
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# PRD calculation mirrors (pure functions; rounding is round-half-up exactly
# as the PRD pins it)
# ---------------------------------------------------------------------------

def round_half_up_cents(value) -> int:
    """Round a (possibly fractional) cent figure half-up to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def household_cap_cents(household_size: int) -> int:
    """cap = BASE_CAP_CENTS + (size - REF_HOUSEHOLD_SIZE) * PER_MEMBER_ADJUST_CENTS"""
    return BASE_CAP_CENTS + (household_size - REF_HOUSEHOLD_SIZE) * PER_MEMBER_ADJUST_CENTS


def need_tier_half_cap_cents(household_size: int) -> int:
    """Half the household cap, rounded half-up to a whole cent."""
    return round_half_up_cents(household_cap_cents(household_size) * NEED_HIGH_FRACTION)


def need_tier_for(household_income_cents: int, household_size: int) -> str:
    """HIGH when income <= half the household cap, else STANDARD."""
    return "HIGH" if household_income_cents <= need_tier_half_cap_cents(household_size) else "STANDARD"


def academic_index_for(gpa_scaled: int, test_score=None) -> int:
    """min(AI_CAP, gpa_scaled * AI_GPA_WEIGHT + floor(test_score / AI_TEST_DIVISOR));
    a null test score contributes 0."""
    test_component = 0 if test_score is None else math.floor(test_score / AI_TEST_DIVISOR)
    return min(AI_CAP, gpa_scaled * AI_GPA_WEIGHT + test_component)


def efc_provisional_cents(household_income_cents: int, household_size: int) -> int:
    """PROVISIONAL variant: self-reported figures, no asset add-back."""
    allowance = P_ALLOW_BASE_CENTS + household_size * P_ALLOW_PER_MEMBER_CENTS
    return max(0, round_half_up_cents((household_income_cents - allowance) * P_RATE))


def efc_verified_cents(verified_income_cents: int, verified_assets_cents: int,
                       verified_household_size: int) -> int:
    """VERIFIED variant: 12% asset add-back rounded half-up BEFORE the rate."""
    asset_addback = round_half_up_cents(verified_assets_cents * V_ASSET_RATE)
    allowance = V_ALLOW_BASE_CENTS + verified_household_size * V_ALLOW_PER_MEMBER_CENTS
    base = verified_income_cents + asset_addback - allowance
    return max(0, round_half_up_cents(base * V_RATE))


def aid_components(coa_cents: int, efc_cents: int, aid_policy: str) -> dict:
    """Pinned composition waterfall: need -> work-study -> loan -> grant remainder.

    Each component is rounded half-up BEFORE its cap; grant is never rounded.
    """
    need = max(0, coa_cents - efc_cents)
    work_study = min(WORK_STUDY_CAP_CENTS, round_half_up_cents(need * WORK_STUDY_RATE))
    if aid_policy == "NO_LOAN":
        loan = 0
    else:
        loan = min(LOAN_CAP_CENTS, round_half_up_cents((need - work_study) * LOAN_RATE))
    grant = need - work_study - loan
    return {
        "need_cents": need,
        "work_study_cents": work_study,
        "loan_cents": loan,
        "grant_cents": grant,
    }


def priority_score_for(application: dict, college_aid_policy: str,
                       referral_converted: bool = False) -> int:
    """Regular-pool ordering score for (application, viewing college)."""
    score = application["academic_index"] or 0
    if application.get("prep_alum"):
        score += PREP_ALUM_BONUS
    if referral_converted:
        score += REFERRAL_BONUS
    if college_aid_policy == "NO_LOAN" and application.get("need_tier") == "HIGH":
        score += NEED_AWARE_BONUS
    return score


def discrepancy_outcome(reported_income_cents: int, verified_income_cents: int) -> str:
    """VERIFIED unless the absolute difference is STRICTLY greater than ten
    percent of the reported figure (exact integer cross-multiplication)."""
    if reported_income_cents == 0:
        return "VERIFIED" if verified_income_cents == 0 else "DISCREPANCY"
    diff = abs(verified_income_cents - reported_income_cents)
    return "DISCREPANCY" if diff * 100 > reported_income_cents * DISCREPANCY_MAX_PCT else "VERIFIED"


def rate_bp(numerator: int, denominator: int) -> int:
    """Basis-point rate, round half-up; 0 when the denominator is 0."""
    if denominator == 0:
        return 0
    return round_half_up_cents(Decimal(numerator * RATE_SCALE_BP) / Decimal(denominator))
