"""Platform-wide constants for the Legal Research Citator API.

Every symbolic constant referenced by the PRD is pinned here exactly once.
"""

# --- Logical clock -----------------------------------------------------------
# PRD 2.4: startup default reads exactly 2026-09-01T00:00:00Z and never falls
# back to wall-clock time.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Billing -----------------------------------------------------------------
# PRD 3.6 names NET_TERMS_DAYS symbolically ("the platform's standard
# net-terms period") without giving a number; pinned here.
NET_TERMS_DAYS = 30

# --- Usage bulk-rate defaults (PRD 3.4 / scaffold usage_scope_monitoring) ----
DEFAULT_BULK_HOURLY_LIMIT = 100
DEFAULT_BULK_DAILY_LIMIT = 500

# --- Citator signal thresholds (PRD 2.6) -------------------------------------
SIGNAL_RED_MIN = 80
SIGNAL_YELLOW_MIN = 40

# --- Citator treatment/depth weight matrix (PRD 2.6) --------------------------
CITATOR_WEIGHTS = {
    "OVERRULED":       {"EXAMINED": 100, "DISCUSSED": 80, "CITED": 50, "MENTIONED": 20},
    "CRITICIZED":      {"EXAMINED": 60,  "DISCUSSED": 45, "CITED": 25, "MENTIONED": 10},
    "QUESTIONED":      {"EXAMINED": 50,  "DISCUSSED": 35, "CITED": 20, "MENTIONED": 8},
    "DISTINGUISHED":   {"EXAMINED": 20,  "DISCUSSED": 15, "CITED": 8,  "MENTIONED": 3},
    "FOLLOWED":        {"EXAMINED": -30, "DISCUSSED": -20, "CITED": -10, "MENTIONED": -4},
    "CITED_NEUTRALLY": {"EXAMINED": 0,   "DISCUSSED": 0,  "CITED": 0,  "MENTIONED": 0},
}

# --- Roles (PRD 2.1) ----------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "ContentIngester",
    "CitatorAnalyst",
    "AttorneyEditor",
    "LicensingManager",
    "FirmAdmin",
    "Researcher",
    "BillingAdmin",
    "ComplianceOfficer",
)

# --- Enum domains --------------------------------------------------------------
SOURCE_TYPES = ("COURT", "LEGISLATURE", "AGENCY")
DOCUMENT_TYPES = ("CASE", "STATUTE", "REGULATION")
INGESTION_STATUSES = ("RECEIVED", "PUBLISHED")
VISIBILITY_STATUSES = ("PUBLIC", "SEALED", "REMOVED")
CITATOR_SIGNALS = ("GREEN", "YELLOW", "RED")
TREATMENTS = ("OVERRULED", "CRITICIZED", "QUESTIONED", "DISTINGUISHED", "FOLLOWED", "CITED_NEUTRALLY")
DEPTHS = ("EXAMINED", "DISCUSSED", "CITED", "MENTIONED")
REFERENCE_STATUSES = ("ACTIVE", "INACTIVE")
TOPIC_CODES = ("LITIGATION", "CORPORATE", "TAX", "IP", "CRIMINAL", "FAMILY")
PRACTICE_AREAS = ("LITIGATION", "CORPORATE", "TAX", "IP", "CRIMINAL", "FAMILY")
PLAN_PRACTICE_AREAS = ("LITIGATION", "CORPORATE", "TAX", "IP", "CRIMINAL", "FAMILY", "ALL")
JURISDICTION_SCOPES = ("FEDERAL", "STATE", "NATIONAL")
FIRM_SIZE_TIERS = ("SOLO", "SMALL", "MID", "LARGE")
BILLING_MODELS = ("FLAT_RATE", "TRANSACTIONAL")
SCOPE_ENFORCEMENTS = ("HARD", "SOFT")
ACCOUNT_TYPES = ("LAW_FIRM", "GOVERNMENT", "CORPORATE")
SUBSCRIPTION_STATUSES = ("ACTIVE", "SUSPENDED", "CANCELLED")
SUBSCRIPTION_TARGET_STATUSES = ("SUSPENDED", "ACTIVE", "CANCELLED")
SUSPENSION_REASONS = ("MANUAL", "INVOICE_OVERDUE")
SEAT_ACTIONS = ("ASSIGN", "RELEASE")
EVENT_TYPES = ("SEARCH", "DOC_VIEW")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "OVERDUE", "PAID", "VOID")
INVOICE_TARGET_STATUSES = ("ISSUED", "PAID", "VOID")
ROYALTY_BASES = ("PER_VIEW", "REVENUE_SHARE")
ORDER_SCOPES = ("SEAL", "REMOVE")
ORDER_STATUSES = ("RECEIVED", "APPLIED", "REVERSED")
ORDER_TARGET_STATUSES = ("APPLIED", "REVERSED")
HEADNOTE_STATUSES = ("DRAFT", "IN_REVIEW", "PUBLISHED", "RETRACTED")
DECISIONS = ("APPROVE", "REJECT")
DIRECTIONS = ("FROM", "TO")

# --- Pagination (PRD 2.3) ------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
