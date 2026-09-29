"""Domain thresholds and time helpers taken from the PRD's stated numbers."""
from datetime import datetime, timedelta, timezone

# --- logical clock (PRD §2.4) ---------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# --- conformance scoring (PRD §3.4) --------------------------------------
AREA_WEIGHTS = {
    "AUTHENTICATION": 0.30,
    "SOFTWARE_UPDATE": 0.30,
    "DATA_PROTECTION": 0.25,
    "VULN_DISCLOSURE": 0.15,
}
AREA_FLOOR_SCORE = 60.00
GATE_CAP_SCORE = 65.00
GRADE_A_MIN = 90.00
GRADE_B_MIN = 80.00

# --- issuance fee (PRD §3.6) --------------------------------------------
RENEWAL_SUPPLEMENT_CENTS = 12000
SURCHARGE_BAND_1_CENTS = 50000
SURCHARGE_BAND_2_CENTS = 150000
SURCHARGE_RATE_MID = 0.10
SURCHARGE_RATE_HIGH = 0.18

# --- enforcement penalties (PRD §3.9) -----------------------------------
STATUTORY_PER_UNIT_CENTS = {
    "UNAUTHORIZED_DISPLAY": 4200,
    "EXPIRED_LABEL_DISPLAY": 2750,
    "FALSE_CLAIM": 6100,
}
CHANNEL_FACTOR = {"IN_STORE": 1.15, "ONLINE": 1.35}
AGGRAVATION_STEP = 0.25
AGGRAVATION_CAP = 2.00
STATUTORY_CAP_CENTS = 5000000
REVENUE_RATE = 0.0004
REVENUE_CAP_CENTS = 25000000

# --- manufacturer ledger / standing (PRD §3.9) ---------------------------
DELINQUENCY_THRESHOLD_CENTS = 25000
BARRED_UPHELD_CASE_COUNT = 3

# --- retailer participation (PRD §3.8) -----------------------------------
GOLD_MIN_DISPLAYS = 2
PLATINUM_MIN_DISPLAYS = 5
DISPLAY_CHANGEOVER_BUFFER_DAYS = 7

# --- program evaluation (PRD §3.10) --------------------------------------
PARTICIPATION_TARGET_PCT = 40.00
RECOGNITION_TARGET_PCT = 35.00

THRESHOLDS = {
    "AREA_FLOOR_SCORE": AREA_FLOOR_SCORE,
    "GATE_CAP_SCORE": GATE_CAP_SCORE,
    "GRADE_A_MIN": GRADE_A_MIN,
    "GRADE_B_MIN": GRADE_B_MIN,
    "DELINQUENCY_THRESHOLD_CENTS": DELINQUENCY_THRESHOLD_CENTS,
    "BARRED_UPHELD_CASE_COUNT": BARRED_UPHELD_CASE_COUNT,
    "GOLD_MIN_DISPLAYS": GOLD_MIN_DISPLAYS,
    "PLATINUM_MIN_DISPLAYS": PLATINUM_MIN_DISPLAYS,
    "PARTICIPATION_TARGET_PCT": PARTICIPATION_TARGET_PCT,
    "RECOGNITION_TARGET_PCT": RECOGNITION_TARGET_PCT,
}

# --- shared literals used by fixtures ------------------------------------
TEST_DEFAULTS = {
    "TIER_VALIDITY_DAYS": 365,
    "MIN_OVERALL_SCORE": 80.80,
    "UNVERIFIED_WEIGHT_FACTOR": 0.60,
    "ISSUANCE_BASE_FEE_CENTS": 40000,
    "MAX_DEFICIENCY_ROUNDS": 2,
    "MIN_SUPPORT_PERIOD_DAYS": 730,
    "SUPPORT_PERIOD_END": "2030-01-01T00:00:00Z",
    "TOTAL_BENCH_HOURS": 240,
    "CONCURRENT_BENCH_CAPACITY": 2,
    "SMALL_REVENUE_CENTS": 250000000,
    "LARGE_REVENUE_CENTS": 9800000000,
}


# --- instant helpers -----------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant the API emits or a test supplies."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso_millis(moment: datetime) -> str:
    """Render an instant the way the PRD requires: UTC, three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def canonical_instant(value):
    """Normalise an emitted or supplied instant to three-fractional-digit UTC.

    Equality assertions on instants must not fail on fractional-second width
    alone, so both sides of a comparison are funnelled through this.
    """
    if value is None:
        return None
    return iso_millis(parse_instant(value))


def plus_days(value: str, days: float) -> str:
    """Exact day arithmetic: add `days` periods of 86400 seconds (PRD §2.9)."""
    return iso_millis(parse_instant(value) + timedelta(seconds=days * SECONDS_PER_DAY))


def plus_seconds(value: str, seconds: float) -> str:
    return iso_millis(parse_instant(value) + timedelta(seconds=seconds))


def minus_days(value: str, days: float) -> str:
    return plus_days(value, -days)
