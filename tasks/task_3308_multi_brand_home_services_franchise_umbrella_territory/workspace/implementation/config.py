"""Domain constants for the Franchise Umbrella & Territory Administration API.

Every value here is transcribed literally from PRD.md / SCAFFOLD.yaml.
"""

API_PREFIX = "/franchise"

# PRD 2.1 -- exactly three declared roles.
ROLES = ("FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor")

# PRD 2.13 -- logical clock default; never falls back to wall-clock time.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# PRD 2.6 -- franchisor protected-household cap, across all brands.
HOUSEHOLD_CAP = 250000

# SCAFFOLD notes -- logical-hour windows (all integers).
REFERRAL_EXPIRY_HOURS = 168
ALLOCATION_HOLD_HOURS = 26
STANDARDS_REMEDIATION_HOURS = 168

# PRD 3.7 -- renewal window: strictly before (clock + 90 days).
RENEWAL_WINDOW_DAYS = 90
# PRD 3.8 -- audit reopen window: strictly before (conducted + 24 hours).
AUDIT_REOPEN_HOURS = 24

# ---------------------------------------------------------------------------
# Enumerations (PRD 2.4, 2.6, 2.7, 3.4, 3.6, 3.9, 3.10)
# ---------------------------------------------------------------------------
TRADES = ("PLUMBING", "ELECTRICAL", "HVAC", "RESTORATION", "CLEANING", "PEST", "APPLIANCE")
CERTIFICATION_LEVELS = ("APPRENTICE", "JOURNEYMAN", "MASTER")
CERT_RANK = {"APPRENTICE": 0, "JOURNEYMAN": 1, "MASTER": 2}
ENTITY_TYPES = ("LLC", "CORPORATION", "SOLE_PROPRIETOR", "PARTNERSHIP")
FRANCHISEE_STATUSES = ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")

TERRITORY_STATUSES = (
    "DEFINED", "OFFERED", "AWARDED", "ACTIVE",
    "EXPANSION_REQUESTED", "PENDING_REALLOCATION", "RECLAIMED",
)
TERRITORY_HOLDING_STATUSES = ("AWARDED", "ACTIVE", "EXPANSION_REQUESTED")

AGREEMENT_LIFECYCLE = (
    "DRAFT", "OFFERED", "ACTIVE", "RENEWAL_PENDING",
    "TRANSFER_PENDING", "TERMINATED", "EXPIRED", "SUSPENDED",
)
AGREEMENT_TERMINAL = ("TERMINATED", "EXPIRED")
AGREEMENT_LIVE = ("ACTIVE", "RENEWAL_PENDING", "TRANSFER_PENDING")
STANDARDS_STATUSES = ("COMPLIANT", "WATCH", "REMEDIATION_REQUIRED", "DEFAULT")
STANDARDS_RANK = {"COMPLIANT": 0, "WATCH": 1, "REMEDIATION_REQUIRED": 2, "DEFAULT": 3}

AUDIT_STATUSES = ("SCHEDULED", "CONDUCTED", "PUBLISHED", "SUPERSEDED")
REMEDIATION_STATUSES = (
    "NONE", "OPEN", "SUBMITTED", "RE_VERIFICATION",
    "RESOLVED", "ESCALATED", "DEFAULTED",
)
REMEDIATION_OPEN_SET = ("OPEN", "SUBMITTED", "RE_VERIFICATION", "ESCALATED")
AUDIT_KINDS = ("ANNOUNCED", "MYSTERY_SHOP")

REFERRAL_STATUSES = ("PENDING", "ACCEPTED", "DECLINED", "COMPLETED", "DISPUTED", "SETTLED")
LEAD_SOURCES = ("CALL_CENTER", "WEB", "NATIONAL_ACCOUNT")
LEAD_STATUSES = ("RECEIVED", "ALLOCATED", "CONVERTED", "RELEASED", "EXPIRED")
INCOME_BANDS = ("BAND_1", "BAND_2", "BAND_3", "BAND_4")

ACCOUNT_TYPES = ("NATIONAL_ACCOUNT", "PROPERTY_MANAGER")
ACCOUNT_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
WORK_ORDER_SOURCES = (
    "NATIONAL_ACCOUNT", "PROPERTY_MANAGER", "CALL_CENTER_LEAD",
    "CROSS_BRAND_REFERRAL", "DIRECT",
)
WORK_ORDER_PRIORITIES = ("EMERGENCY", "URGENT", "STANDARD")
WORK_ORDER_STATUSES = ("CREATED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "SLA_BREACHED")

STATEMENT_STATUSES = ("DRAFT", "ISSUED", "PAID", "VOIDED")

ASSIGNMENT_KINDS = ("INITIAL_AWARD", "RESALE", "TRANSFER", "TERRITORY_REALLOCATION")
TRANSFER_KINDS = ("RESALE", "TRANSFER", "TERRITORY_REALLOCATION")
TRANSFER_STATUSES = (
    "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
    "APPROVED", "REJECTED", "CLOSED",
)
TRANSFER_OPEN_SET = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED")

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------
# standards_audit_score_calculation
ANNOUNCED_WEIGHT = "1.00"
MYSTERY_SHOP_WEIGHT = "0.80"
CRITICAL_PENALTY_PER_FINDING = "7.5"
PASS_MIN = "85.0"
WATCH_MIN = "70.0"

# labor_charge_calculation
HOURLY_RATE_CENTS = {"EMERGENCY": 18500, "URGENT": 18500, "STANDARD": 14500}
PRIORITY_HOURS_SCALE = {"EMERGENCY": "0.5", "URGENT": "0.75", "STANDARD": "1.0"}
SOURCE_MULTIPLIER = {
    "NATIONAL_ACCOUNT": "0.90",
    "PROPERTY_MANAGER": "0.95",
    "CALL_CENTER_LEAD": "1.00",
    "CROSS_BRAND_REFERRAL": "0.85",
    "DIRECT": "1.00",
}

# lead_cost_calculation
BAND_BASE_CENTS = {"BAND_1": 2500, "BAND_2": 4000, "BAND_3": 6500, "BAND_4": 9000}
VALUE_UNIT_CENTS = 100000
VALUE_UNIT_RATE_CENTS = 250
MULTI_BRAND_MIN = 3
MULTI_BRAND_DISCOUNT = "0.85"

# transfer_fee_calculation -- the recipe is referenced by the scaffold and the
# PRD but never given a formula, so the fee is 0 for every kind (documented in
# the summary as an interpretation).
TRANSFER_FEE_RATE = {
    "RESALE": "0",
    "TRANSFER": "0",
    "TERRITORY_REALLOCATION": "0",
}

# ---------------------------------------------------------------------------
# Request-envelope / documented-role literals
# ---------------------------------------------------------------------------
# PRD 2.11 -- opaque operator identity used as the franchisor-side principal
# operator of a franchisee (remediation owner, transfer submission check).
FRANCHISOR_OPERATOR_PREFIX = "op_"