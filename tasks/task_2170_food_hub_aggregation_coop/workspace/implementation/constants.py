"""Domain constants.

The three constants the scaffold names but never binds are bound by PRD.md,
which is the contract:
  MAX_REVIEW_CYCLES     = 3      (PRD 3.1: "sent back for changes at most three times")
  WRITE_OFF_GRACE_DAYS  = 30     (PRD 3.8: "write-off grace period of 30 days")
  TEMP_TOLERANCE_C      = 2.0    (PRD 3.6: "tolerance of 2.0 degrees Celsius",
                                  compared with a strict '>' so a reading exactly
                                  at setpoint + tolerance is WITHIN tolerance)
"""

# ---- roles -----------------------------------------------------------------
ROLE_HUB_ADMIN = "HubAdmin"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_PRODUCER = "Producer"
ROLE_BUYER = "Buyer"
ROLE_BOARD = "BoardDirector"
ALL_ROLES = (ROLE_HUB_ADMIN, ROLE_COMPLIANCE, ROLE_PRODUCER, ROLE_BUYER, ROLE_BOARD)

# ---- enums -----------------------------------------------------------------
PRODUCER_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                   "ACTIVE", "SUSPENDED", "TERMINATED")
DOC_TYPES = ("GAP_AUDIT", "LIABILITY_INSURANCE", "HACCP_PLAN", "ORGANIC_CERT", "WATER_TEST")
DOC_STATES = ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED", "SUPERSEDED")
UNITS_OF_MEASURE = ("CASE", "LB", "EACH")
STORAGE_CLASSES = ("AMBIENT", "CHILL", "FROZEN")
PRODUCT_STATES = ("DRAFT", "LISTED", "DELISTED")
BUYER_TYPES = ("SCHOOL_DISTRICT", "HOSPITAL", "UNIVERSITY", "CORRECTIONS")
PAYMENT_TERMS_DAYS = (15, 30, 45)
FULFILLMENT_STATES = ("DRAFT", "AGGREGATED", "SCHEDULED", "IN_TRANSIT", "DELIVERED", "CLOSED")
SETTLEMENT_STATES = ("UNBILLED", "INVOICED", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF")
LINE_STATES = ("PENDING", "ALLOCATED", "SHORT", "DELIVERED", "SETTLED")
ALLOCATION_STATES = ("RESERVED", "STAGED", "DELIVERED", "SHORT_CLOSED", "REVERSED")
DOCK_SLOT_STATES = ("OPEN", "FULL", "CLOSED")
RISK_CLASSES = ("RAW_ANIMAL", "PRODUCE", "READY_TO_EAT")
APPOINTMENT_STATES = ("BOOKED", "RECEIVED", "NO_SHOW", "CANCELLED")
APPOINTMENT_OUTCOMES = ("RECEIVED", "NO_SHOW", "CANCELLED")
ROUTE_STATES = ("PLANNED", "LOADED", "DISPATCHED", "COMPLETED")
CLAIM_STATES = ("FILED", "APPROVED", "DENIED", "WITHDRAWN")
CLAIM_REASONS = ("TEMP_ABUSE", "DAMAGE", "SPEC_MISMATCH", "SHORT_COUNT", "LATE_DELIVERY")
CLAIM_DECISIONS = ("APPROVE", "DENY", "WITHDRAW")
CYCLE_STATES = ("PROPOSED", "RATIFIED", "DISTRIBUTED", "CANCELLED")
CYCLE_DECISIONS = ("RATIFY", "REJECT")
REVIEW_DECISIONS = ("APPROVE", "REQUEST_CHANGES", "SUSPEND", "REINSTATE", "TERMINATE")
DOC_DECISIONS = ("VERIFY", "REJECT")

# ---- compliance ------------------------------------------------------------
REQUIRED_DOC_TYPES = ("GAP_AUDIT", "LIABILITY_INSURANCE", "HACCP_PLAN")
AUDITED_EXTRA_DOC_TYPES = ("ORGANIC_CERT", "WATER_TEST")
MAX_REVIEW_CYCLES = 3

# ---- money -----------------------------------------------------------------
BP_DENOMINATOR = 10000
MARGIN_BP_CEILING = 1800
TIER_1_UPPER_EXCLUSIVE_CENTS = 50000
TIER_2_UPPER_EXCLUSIVE_CENTS = 200000
TIER_3_UPPER_EXCLUSIVE_CENTS = 500000
TIER_BP = (1800, 1500, 1250, 1000)
MIN_ORDER_MARGIN_CENTS = 2500
WRITE_OFF_GRACE_DAYS = 30

# ---- shrink ----------------------------------------------------------------
TEMP_ABUSE_EXCURSION_BP = 2000
TEMP_ABUSE_NO_EXCURSION_BP = 8000
DAMAGE_BP = 5000
SPEC_MISMATCH_BP = 9000
SHORT_COUNT_BP = 10000
LATE_DELIVERY_BP = 0
AUDITED_TIER_RELIEF_BP = 1500
PRODUCER_FAULT_CAP_BP = 9000

# ---- cold chain ------------------------------------------------------------
TEMP_TOLERANCE_C = 2.0

# ---- dock ------------------------------------------------------------------
DEFAULT_SANITATION_BUFFER_MINUTES = 45

# ---- equity / governance ---------------------------------------------------
EQUITY_SHARE_UNIT_CENTS = 25000
MAX_VOTING_SHARES = 10
PATRONAGE_CAP_BP = 3000
FISCAL_YEAR_MIN = 2000
FISCAL_YEAR_MAX = 2100

# ---- pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
