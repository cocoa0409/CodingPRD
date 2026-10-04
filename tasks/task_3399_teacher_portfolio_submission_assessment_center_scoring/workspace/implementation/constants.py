"""All PRD-pinned constants for the Teacher Portfolio Certification API.

Every constant referenced anywhere in the implementation is defined exactly
once here, with the PRD/SCAFFOLD value.
"""
from decimal import Decimal

# Logical clock startup default (PRD section 2.4)
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Score scale / grid (PRD section 2.6)
SCORE_MIN = Decimal("0.00")
SCORE_MAX = Decimal("4.00")
SCORE_STEP = Decimal("0.25")

# Weighted aggregation (PRD section 2.6): weights sum to exactly 1.000;
# per-component contribution round-half-up to 3dp BEFORE summing; total 2dp.
WEIGHT_SUM_REQUIRED = Decimal("1.000")
CONTRIBUTION_QUANT = Decimal("0.001")
TOTAL_QUANT = Decimal("0.01")
SCORE_QUANT = Decimal("0.01")

# Certification validity / renewal (PRD section 3.7)
VALIDITY_DAYS = 1825
MIN_RENEWAL_HOURS = 45
RENEWAL_LOOKBACK_DAYS = 90
RENEWAL_GRACE_DAYS = 30

# Inter-rater reliability (PRD section 3.5)
IRR_WINDOW = 10
IRR_EXACT_FLOOR = Decimal("0.70")
ADJACENT_BAND = Decimal("0.25")

# Calibration (PRD section 3.5)
REQUIRED_CALIBRATION_PASSES = 2
MAX_CALIBRATION_FAILURES = 3

# Double-blind divergence (PRD section 3.6)
DIVERGENCE_TOLERANCE = Decimal("0.50")

# Defaults (SCAFFOLD entities)
DEFAULT_MAX_ATTEMPTS_PER_COMPONENT = 2
DEFAULT_FTE_FRACTION = 1.0
DEFAULT_TOLERANCE = 0.25
DEFAULT_EARLY_BIRD_MULTIPLIER = 1.10

# Artifact limits (PRD section 3.3)
VIDEO_MAX_MB = 500
DOC_MAX_MB = 50
VIDEO_MAX_MINUTES = 15

# Assessment sessions (PRD section 3.4)
SESSION_DURATION_MINUTES = 120

# Eligibility (PRD section 3.2)
MIN_TEACHING_YEARS = 3
FTE_MIN = 0.5
FTE_MAX = 1.0

# Pagination (PRD section 2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Role names (PRD section 2.1), spelled exactly as the API expects them
ROLE_ANONYMOUS = "Anonymous"
ROLE_CANDIDATE = "Candidate"
ROLE_ASSESSOR = "Assessor"
ROLE_SCORING_ADMIN = "ScoringAdministrator"
ROLE_BOARD_ADMIN = "BoardAdministrator"
ROLE_INCENTIVE_ADMIN = "IncentiveAdministrator"
ALL_ROLES = (
    ROLE_ANONYMOUS,
    ROLE_CANDIDATE,
    ROLE_ASSESSOR,
    ROLE_SCORING_ADMIN,
    ROLE_BOARD_ADMIN,
    ROLE_INCENTIVE_ADMIN,
)
