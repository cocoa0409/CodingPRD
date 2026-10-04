"""Platform constants.

Transcribed from SCAFFOLD.yaml Table 3 (Calculation Rules Table) "constants"
blocks and the state-machine/validation prose of PRD sections 2-3.
"""

import datetime

# --- Fixed logical clock ---
# PRD 2.4: at startup the logical clock reads exactly 2026-09-01T00:00:00Z and
# never falls back to real wall-clock time.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Standard set size (PRD 3.2) ---
CARDS_PER_SET = 100

# --- print_run_projection (SCAFFOLD calc #1) ---
SALES_HISTORY_UNITS_PER_CLAIM = 1000
SALES_HISTORY_MIN_RECORDS = 3
MARKET_DEMAND_UNITS_PER_CASE = 10
CLAIM_BACKDATE_WINDOW_DAYS = 30
PROJECTION_FLOOR = {"BASE": 1000, "INSERT": 100, "PREMIUM": 25}
PROJECTION_CEILING = {"BASE": 50000, "INSERT": 10000, "PREMIUM": 2000}
PROJECTION_MULTIPLE_OF = {"BASE": 500, "INSERT": 100, "PREMIUM": 25}
BRAND_DIRECTIVE_BASE = {"BASE": 12000, "INSERT": 3000, "PREMIUM": 400}

# --- print_run_quality_floor (SCAFFOLD calc #2) ---
REORDER_HIT_RATE = 0.005

# --- quality_claim_weight (SCAFFOLD calc #3) ---
SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}

# --- autograph_royalty_charge (SCAFFOLD calc #4) ---
SIGNER_ROYALTY_CENTS = 750

# --- redemption substitution (SCAFFOLD calc #5 / #8) ---
SUBSTITUTION_DIVERGENCE_CENTS = 250000
SUBSTITUTION_RATIO_LOW = 1.00
SUBSTITUTION_RATIO_HIGH = 1.25
SUBSTITUTION_DEADLINE_DAYS_LOW = 365
SUBSTITUTION_DEADLINE_DAYS_HIGH = 730

# --- distribution_share_projection (SCAFFOLD calc #6) ---
CASES_PER_SET = 1

# --- signer logistics ---
# ship_date = scheduled_on - SIGNER_SHIP_LEAD_DAYS (SCAFFOLD SigningSession).
SIGNER_SHIP_LEAD_DAYS = 30

# --- print-run decision validity window (SCAFFOLD validations priority 10) ---
PRINT_DECISION_VALIDITY_DAYS = 30

# --- quality recall loop (SCAFFOLD DistributionAllocation recall) ---
# The recall loop recurses while sum(affected_quantity) of APPROVED claims
# strictly exceeds this threshold (PRD 3.8).  The scaffold names the
# threshold but does not pin a value; 0 makes every single approved claim
# extend the cascade, which is the conservative reading of "exceeds".
QUALITY_RECALL_THRESHOLD = 0

# --- Enum vocabularies (SCAFFOLD Table 1 constraints) ---
EXCLUSIVITY_SCOPES = ("EXCLUSIVE", "NON_EXCLUSIVE")
LICENSE_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
LINE_KINDS = ("BASE", "INSERT", "PREMIUM")
LINE_STATUSES = ("PLANNING", "READY_FOR_APPROVAL", "APPROVED", "IN_PRODUCTION", "PACKED_OUT")
SET_TIERS = ("BASE", "INSERT", "PREMIUM")
PRINT_RUN_STATUSES = ("UNDECIDED", "LOCKED", "DISCLOSED", "UNDISCLOSED")
PACK_CONFIG_STATUSES = ("PROPOSED", "PUBLISHED", "SUPERSEDED")
SIGNER_KINDS = ("PLAYER_ASSOCIATION", "INDEPENDENT")
SIGNING_SESSION_STATUSES = ("SCHEDULED", "STOCK_PREPARED", "STOCK_SHIPPED", "COMPLETED", "CANCELLED")
ARTWORK_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")
ARTWORK_DECISIONS = ("APPROVE", "REJECT")
PRINT_DECISION_AUTHORITIES = ("SALES_HISTORY", "MARKET_DEMAND", "BRAND_DIRECTIVE")
PRINT_DECISION_STATUSES = ("PROPOSED", "APPROVED", "SUPERSEDED")
REDEMPTION_STATUSES = ("ISSUED", "FULFILLED", "CLOSED", "CANCELLED")
NOTIFICATION_STATUSES = ("ISSUED", "ACKNOWLEDGED", "SETTLED", "RESOLVED")
CHANNELS = ("HOBBY", "MASS", "DIRECT")
ALLOCATION_STATUSES = ("RESERVED", "UTF", "SHIPPED", "RECALLED")
CLAIM_TYPES = ("MISPRINT", "DAMAGE", "MISSING_HIT")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
QUALITY_CLAIM_STATUSES = ("FILED", "UNDER_REVIEW", "APPROVED", "CREDITED", "DENIED")
BREACH_REASONS = ("UNDISCLOSED_PRINT_RUN", "NO_REPLACEMENT_POLICY")
COMPLAINT_STATUSES = ("OPEN", "UNDER_REVIEW", "APPROVED", "REJECTED", "SETTLED")
SIGNER_ATTENDANCE = ("ATTENDED", "NO_SHOW")

# --- Roles (PRD 2.1 / SCAFFOLD Table 7) ---
ROLES = (
    "LicensingManager",
    "ProductManager",
    "ProductionPlanner",
    "SigningCoordinator",
    "AuthenticationOfficer",
    "LicensorApprover",
    "RedemptionFulfilmentAnalyst",
    "DistributionManager",
    "QualityAnalyst",
    "CollectorSupportSpecialist",
    "PlatformAdmin",
)

# --- Pagination (SCAFFOLD response_envelope.pagination_defaults) ---
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def parse_dt(value):
    """Parse a client-supplied ISO-8601 instant into a naive-UTC datetime.

    Returns None when the value is absent or not a string that parses; callers
    decide whether that is ERR_INVALID_REQUEST or an optional field.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def fmt_dt(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)