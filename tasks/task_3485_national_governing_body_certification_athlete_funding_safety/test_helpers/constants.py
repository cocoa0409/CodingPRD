"""Domain thresholds — every numeric constant stated in the PRD.

Single source of truth for stage-2 tests; values are the PRD literals.
Also provides the round-half-up helper matching the PRD rounding rule
("rounded half up to two decimal places").
"""
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock (PRD logical-clock section)
# ---------------------------------------------------------------------------

CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Compliance score (certification cycles)
# ---------------------------------------------------------------------------

SCORE_WEIGHT_GOVERNANCE = 0.40
SCORE_WEIGHT_ATHLETE_REP = 0.35
SCORE_WEIGHT_FINANCIAL = 0.25
COMPLIANCE_PASS_THRESHOLD = 70
COMPLIANCE_EXCELLENT_THRESHOLD = 85
REMEDIATION_BONUS_CAP = 10
CYCLE_MAX_DURATION_DAYS = 120

# ---------------------------------------------------------------------------
# Funding points (performance results -> agreement points)
# ---------------------------------------------------------------------------

PLACING_POINTS = {1: 40, 2: 32, 3: 26, 4: 20, 5: 16, 6: 12, 7: 8, 8: 4}
EVENT_MULTIPLIER = {"A": 1.5, "B": 1.25, "C": 1.0}
EVENT_MULTIPLIER_A = 1.5
EVENT_MULTIPLIER_B = 1.25
EVENT_MULTIPLIER_C = 1.0
RECENCY_FULL_DAYS = 180
RECENCY_HALF_WEIGHT = 0.5
TRAILING_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Tier assignment (inclusive thresholds; exact value qualifies)
# ---------------------------------------------------------------------------

TIER_A_MIN_POINTS = 100
TIER_B_MIN_POINTS = 60
TIER_C_MIN_POINTS = 30
STIPEND_TIER_A_CENTS = 300000
STIPEND_TIER_B_CENTS = 200000
STIPEND_TIER_C_CENTS = 100000
TIER_STIPEND_CENTS = {
    "TIER_A": STIPEND_TIER_A_CENTS,
    "TIER_B": STIPEND_TIER_B_CENTS,
    "TIER_C": STIPEND_TIER_C_CENTS,
    "NONE": 0,
}

# ---------------------------------------------------------------------------
# Insurance eligibility (both boundaries inclusive)
# ---------------------------------------------------------------------------

INSURANCE_MIN_POINTS = 60
INSURANCE_WAIT_DAYS = 30

# ---------------------------------------------------------------------------
# Roster composite ranking and quota bonus
# ---------------------------------------------------------------------------

COMPOSITE_TRIALS_WEIGHT = 0.7
COMPOSITE_SEASON_WEIGHT = 0.3
ALTERNATE_COUNT = 2
QUOTA_BONUS_THRESHOLD = 250
QUOTA_BONUS_SLOTS = 1

# ---------------------------------------------------------------------------
# Revenue split (pinned rounding order: committee, body, athlete remainder)
# ---------------------------------------------------------------------------

COMMITTEE_SHARE_PCT = 0.30
NGB_SHARE_PCT = 0.40
ATHLETE_SHARE_PCT = 0.30
AGENCY_FEE_PCT = 0.10

# ---------------------------------------------------------------------------
# Sport-science hours waterfall caps
# ---------------------------------------------------------------------------

SCIENCE_HOURS_CAP_A = 40
SCIENCE_HOURS_CAP_B = 25
SCIENCE_HOURS_CAP_C = 10
SCIENCE_HOURS_CAPS = {
    "TIER_A": SCIENCE_HOURS_CAP_A,
    "TIER_B": SCIENCE_HOURS_CAP_B,
    "TIER_C": SCIENCE_HOURS_CAP_C,
}

# ---------------------------------------------------------------------------
# Complaint posture
# ---------------------------------------------------------------------------

COMPLAINT_POSTURE_THRESHOLD = 3
COMPLAINT_POSTURE_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Safe-sport validity windows
# ---------------------------------------------------------------------------

SCREENING_VALIDITY_DAYS = 730
TRAINING_VALIDITY_DAYS = 365

# ---------------------------------------------------------------------------
# Selection-procedure temporal gates
# ---------------------------------------------------------------------------

MIN_PUBLISH_LEAD_DAYS = 90
REGISTRATION_CLOSE_BEFORE_TRIALS_DAYS = 14
APPEAL_WINDOW_HOURS = 72

# ---------------------------------------------------------------------------
# Commercial-deal exclusivity (closed interval, mandatory gap)
# ---------------------------------------------------------------------------

DEAL_EXCLUSIVITY_MIN_GAP_DAYS = 1

# ---------------------------------------------------------------------------
# Pagination (PRD pagination section)
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding / computation helpers mirroring the PRD formulas
# ---------------------------------------------------------------------------

def round_half_up(value, places=2):
    """Round half up to `places` decimal places (PRD rounding rule)."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    """Round half up to a whole integer (money shares, in cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def base_points(event_grade: str, placing: int) -> float:
    """PRD base-points rule: placing ladder times grade multiplier."""
    return PLACING_POINTS[placing] * EVENT_MULTIPLIER[event_grade]


def weighted_compliance(governance, athlete_rep, financial) -> float:
    """PRD weighted compliance blend at 2dp round-half-up."""
    return round_half_up(
        SCORE_WEIGHT_GOVERNANCE * governance
        + SCORE_WEIGHT_ATHLETE_REP * athlete_rep
        + SCORE_WEIGHT_FINANCIAL * financial
    )


def remediation_final_score(governance, athlete_rep, financial) -> float:
    """PRD remediation close: +10 to the single lowest component (cap 100),
    ties broken financial first, then athlete_rep, then governance; re-weight."""
    scores = {
        "governance": governance,
        "athlete_rep": athlete_rep,
        "financial": financial,
    }
    # tie-break order pinned: financial, then athlete_rep, then governance
    lowest = min(
        scores,
        key=lambda k: (scores[k], {"financial": 0, "athlete_rep": 1, "governance": 2}[k]),
    )
    scores[lowest] = min(scores[lowest] + REMEDIATION_BONUS_CAP, 100)
    return weighted_compliance(
        scores["governance"], scores["athlete_rep"], scores["financial"]
    )


def tier_for_points(points) -> str:
    """PRD tier thresholds, inclusive."""
    if points >= TIER_A_MIN_POINTS:
        return "TIER_A"
    if points >= TIER_B_MIN_POINTS:
        return "TIER_B"
    if points >= TIER_C_MIN_POINTS:
        return "TIER_C"
    return "NONE"


def composite_score(trials_score, season_points) -> float:
    """PRD roster composite blend at 2dp round-half-up."""
    return round_half_up(
        COMPOSITE_TRIALS_WEIGHT * trials_score
        + COMPOSITE_SEASON_WEIGHT * season_points
    )


def revenue_shares(gross_value_cents: int, basis: str):
    """PRD revenue split with pinned rounding order.

    Returns (committee_share_cents, ngb_share_cents, athlete_share_cents).
    NET_BASIS deducts the 10% agency fee (rounded half up) first.
    """
    if basis == "NET_BASIS":
        fee = round_half_up_int(gross_value_cents * AGENCY_FEE_PCT)
        base = gross_value_cents - fee
    else:
        base = gross_value_cents
    committee = round_half_up_int(base * COMMITTEE_SHARE_PCT)
    ngb = round_half_up_int(base * NGB_SHARE_PCT)
    athlete = base - committee - ngb
    return committee, ngb, athlete
