"""Domain thresholds and defaults from the PRD's calculation rules."""

# Pay rate constants (PRD section 3.10).
BASE_RATE = 6
GOLD_BASE_RATE = 9

TIER_MULT = {"NOVICE": 1.0, "PROFICIENT": 1.25, "EXPERT": 1.5}
STREAK_MULT = {0: 1.0, 1: 1.0, 2: 0.8, 3: 0.5}

# Qualification score constants (PRD section 2.6).
TIER_MIN = {"NOVICE": 5000, "PROFICIENT": 6500, "EXPERT": 8000}
SCORE_BASE = 5000
SCORE_MODULUS = 5000
HANDLE_LEN_FACTOR = 977
HANDLE_CHAR_FACTOR = 31
LANG_CHAR_FACTOR = 17

# Capacity planning constants (PRD section 3.11).
CAPACITY_WEIGHT = {"STANDARD": 1, "SENSITIVE": 2, "RESTRICTED": 3}
MULT = {"ACCEPTED": 1.0, "PROVISIONAL": 1.15, "AT_RISK": 1.35}
REWORK_MULTIPLIER = 1.2
POINT_COST = {"HIGH": 2, "MEDIUM": 3, "FALLBACK": 4}

# Worker selection (PRD section 3.4).
MIN_ACCURACY_PCT = 60.0
COLD_START_AUDIT_FLOOR = 3

# Gold rotation (PRD section 3.7).
GOLD_ROTATION_THRESHOLD = 3

# Rework (PRD section 3.6).
DEFAULT_REWORK_ROUND_LIMIT = 3
DEFAULT_REWORK_WINDOW_SECONDS = 900

# Logical clock (PRD section 2.9).
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "LANGUAGE_CODE": "es-MX",
    "PROGRAM_CODE": "AX-4410",
    "PROGRAM_NAME": "AX Panel",
    "INSTRUCTION_MODEL": "IDEAL_RESPONSE",
    "SENSITIVITY_CLASS": "STANDARD",
    "DEADLINE_UTC": "2026-10-01T00:00:00Z",
    "BLACKOUT_START_UTC": "2026-09-20T00:00:00Z",
    "BLACKOUT_END_UTC": "2026-09-25T00:00:00Z",
    "COVERAGE_START_UTC": "2026-09-01T00:00:00Z",
    "COVERAGE_END_UTC": "2026-09-19T00:00:00Z",
    "MAX_ITEMS": 10,
    "INSTRUCTION_REVISION": 1,
    "FIELD_SCHEMA": ["label"],
    "COMMIT_DEADLINE_SECONDS": 7200,
    "PATIENCE_SECONDS": 600,
    "WEEKLY_EARNING_CAP_CENTS": 9000,
    "COMMITMENT_QUORUM": 3,
    "MIN_CONSENSUS_AGREEMENT": 0.6,
    "CAPACITY_POINTS": 100000,
    "ACCURACY_FLOOR_PCT": 85,
    "ACCURACY_HIGH_WATERMARK_PCT": 95,
    "PANEL_SIZE": 3,
    "GOLD_RATE": 0.0,
    "PAYOUT_CURRENCY": "USD",
    "SETTLEMENT_MIN_CENTS": 1000,
}

# Default profile handles used by fixtures. Each is a distinct WorkerIdentity.
HANDLES = {
    "worker_a": "mira-vega",
    "worker_b": "kevin-lum",
    "worker_c": "linh-tran",
    "worker_d": "diego-salazar",
    "worker_e": "june-osei",
    "worker_f": "tomas-ibarra",
}

# Handles whose deterministic es-MX qualification score lands below the
# PROFICIENT minimum of 6500, used for the sub-tier revocation corner.
SUB_TIER_HANDLE = "sara-kowalski"
SUB_TIER_LANGUAGE = "es-MX"


def compute_qualification_score(handle: str, language_code: str) -> int:
    """The deterministic score of PRD section 2.6, reproducible client-side."""
    inner = (
        len(handle) * HANDLE_LEN_FACTOR
        + sum(ord(c) for c in handle) * HANDLE_CHAR_FACTOR
        + sum(ord(c) for c in language_code) * LANG_CHAR_FACTOR
    )
    return SCORE_BASE + (inner % SCORE_MODULUS)