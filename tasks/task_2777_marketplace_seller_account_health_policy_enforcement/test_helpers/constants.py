"""Named constants harvested verbatim from the PRD narrative.

Nothing here is invented: every figure below is a literal that PRD §2 or §3
states in words or digits. Money is integer cents (§2.6), rates carry four
decimals, points and scores carry two.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# --- Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Registration signal weights (PRD §3.1) --------------------------------
SIGNAL_WEIGHT_TAX_ID = 0.35
SIGNAL_WEIGHT_BANK_TOKEN = 0.45
SIGNAL_WEIGHT_ADDRESS = 0.15
SIGNAL_WEIGHT_EMAIL_DOMAIN = 0.10
SIGNAL_WEIGHT_DEVICE = 0.20
RELATED_LINK_SCORE_CAP = 1.00
RELATED_LINK_MIN_SCORE = 0.35
RELATED_LINK_WATCH_SCORE = 0.60
PUBLIC_EMAIL_DOMAINS = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com")
# "using the fixed order TAX_ID, BANK_TOKEN, ADDRESS, EMAIL_DOMAIN, DEVICE"
MATCHED_SIGNAL_ORDER = ("TAX_ID", "BANK_TOKEN", "ADDRESS", "EMAIL_DOMAIN", "DEVICE")

# --- Policy catalogue bounds (PRD §3.2) ------------------------------------
POLICY_CODE_MIN_LEN = 2
POLICY_CODE_MAX_LEN = 32
BASE_SEVERITY_WEIGHT_MIN = 0.50
BASE_SEVERITY_WEIGHT_MAX = 8.00
DECAY_EXEMPT_CATEGORIES = ("INTELLECTUAL_PROPERTY", "RESTRICTED_PRODUCT")

# --- Health thresholds (PRD §3.4) ------------------------------------------
ODR_THRESHOLD = 0.0100
LATE_SHIPMENT_THRESHOLD = 0.0400
CANCELLATION_THRESHOLD = 0.0250
VALID_TRACKING_FLOOR = 0.9500
RATIO_CAP = 2.0000
PENALTY_WEIGHT_DEFECT = 42.50
PENALTY_WEIGHT_LATE = 24.50
PENALTY_WEIGHT_CANCELLATION = 18.50
PENALTY_WEIGHT_TRACKING = 14.50
HEALTH_SCORE_MAX = 100.00
HEALTH_SCORE_FLOOR = 0.00
TIER_BREACHING_SCORE = 60.00
TIER_AT_RISK_SCORE = 80.00
EVAL_LOOKBACK_DAYS = 90
EVAL_MAX_SNAPSHOTS = 2
# "always emitted in this fixed order"
BREACHED_METRIC_ORDER = (
    "ORDER_DEFECT_RATE",
    "LATE_SHIPMENT_RATE",
    "CANCELLATION_RATE",
    "VALID_TRACKING_RATE",
)
AUTO_EVIDENCE_PREFIX = "HEALTH-EVAL-"

# --- Severity ladder (PRD §3.6) --------------------------------------------
REPEAT_CAP_COUNT = 3
REPEAT_STEP = 0.25
REPEAT_BASE_FACTOR = 1.00
IP_ESCALATION_MULTIPLIER = 1.50
BREACHING_MULTIPLIER = 1.25
SEVERITY_MIN_POINTS = 0.50
SEVERITY_MAX_POINTS = 12.00
DECAY_TIER1_DAYS = 180
DECAY_TIER2_DAYS = 365
DECAY_TIER1_FACTOR = 1.00
DECAY_TIER2_FACTOR = 0.50
DECAY_TIER3_FACTOR = 0.00
LADDER_RESTRICT_POINTS = 4.00
LADDER_SUSPEND_POINTS = 12.00
ACTION_SEVERITY_ORDER = ("WARNING", "LISTING_REMOVAL", "ACCOUNT_SUSPENSION")

# --- Deadlines and windows -------------------------------------------------
APPEAL_WINDOW_DAYS = 30          # PRD §3.6 / §3.8: issued_at plus thirty days
POA_DEADLINE_DAYS = 17           # PRD §3.7: issued_at plus seventeen days
ESCALATION_WINDOW_DAYS = 14      # PRD §3.8: decided_at plus fourteen days
POA_MAX_REVISIONS = 2            # PRD §3.7: revision_count never exceeds 2
APPEAL_REPEAT_DENIAL_THRESHOLD = 2   # PRD §3.8: "reaches 2 or more"

# --- Plan-of-action content thresholds (PRD §3.7) --------------------------
POA_ROOT_CAUSE_MIN_LEN = 40
POA_ROOT_CAUSE_MAX_LEN = 2000
POA_MEASURE_MIN_COUNT = 1
POA_MEASURE_MAX_COUNT = 10
POA_MEASURE_MIN_LEN = 10
POA_MEASURE_MAX_LEN = 500

# --- Appeal content thresholds (PRD §3.8) ----------------------------------
APPEAL_GROUNDS_MIN_LEN = 20
APPEAL_GROUNDS_MAX_LEN = 2000
RATIONALE_MIN_LEN = 20
RATIONALE_MAX_LEN = 2000

# --- Funds (PRD §3.9) ------------------------------------------------------
RESERVE_ROLLING_PCT = {"TIER_1": 0.10, "TIER_2": 0.20, "TIER_3": 0.30}
CLAIM_EXPOSURE_CENTS = 9000
EXPOSURE_MULTIPLIER = {"TIER_1": 1.00, "TIER_2": 1.25, "TIER_3": 1.50}
HOLD_BUFFER_HOURS = 24
FULL_HOLD_COVERAGE_DAYS = 90
RISK_TIER_3_POINTS = 12.00
RISK_TIER_2_POINTS = 4.00

# --- Evidence and violation bounds (PRD §3.5) ------------------------------
EVIDENCE_REFERENCE_MIN_LEN = 3
EVIDENCE_REFERENCE_MAX_LEN = 64

# --- Well-formed identifiers that name no live row -------------------------
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"
UNKNOWN_ID_A = "00000000-0000-4000-8000-000000000000"
UNKNOWN_ID_B = "00000000-0000-4000-8000-00000000dead"
