"""Enumerations and literal value sets declared by the API contract.

Kept as plain tuples/strings so tests can reference a single source of truth for
every enum member the PRD declares.
"""

# ---------------------------------------------------------------- roles (§2.1)
ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
ROLE_TMDL_ANALYST = "TmdlAnalyst"
ROLE_PERMIT_WRITER = "PermitWriter"
ROLE_PERMITTEE = "Permittee"
ROLE_PRODUCER = "Producer"
ROLE_PRACTICE_VERIFIER = "PracticeVerifier"
ROLE_REGISTRY_ADMINISTRATOR = "RegistryAdministrator"

ALL_ROLES = (
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_TMDL_ANALYST,
    ROLE_PERMIT_WRITER,
    ROLE_PERMITTEE,
    ROLE_PRODUCER,
    ROLE_PRACTICE_VERIFIER,
    ROLE_REGISTRY_ADMINISTRATOR,
)

# ------------------------------------------------------------- watershed (§3.1)
POLLUTANTS = ("TOTAL_NITROGEN", "TOTAL_PHOSPHORUS")
PROGRAM_STATUSES = ("PROVISIONAL", "ACTIVE", "ADAPTIVE_HOLD", "TERMINATED")

# ----------------------------------------------------------------- reach (§3.1)
REACH_CLASSES = ("HEADWATER", "MAINSTEM", "COMPLIANCE_POINT", "BACKGROUND")

# ------------------------------------------------------ monitoring sample (§3.1)
QA_STATUSES = ("ACCEPTED", "REJECTED", "PROVISIONAL")

# ------------------------------------------------------- tmdl assessment (§3.2)
ASSESSMENT_STATUSES = (
    "DRAFT",
    "PUBLIC_COMMENT",
    "REVISION",
    "APPROVED",
    "WITHDRAWN",
    "SUPERSEDED",
)

# ------------------------------------------------------ source assessment (§3.3)
SOURCE_TYPES = ("POINT", "NONPOINT")
SOURCE_STATUSES = ("INVENTORIED", "ADJUSTED", "EXCLUDED")

# --------------------------------------------------------- allocation run (§3.3)
ALLOCATION_METHODS = ("PRO_RATA_BY_EXISTING_LOAD", "CONTROLLABILITY_WEIGHTED")
ALLOCATION_RUN_STATUSES = ("ACTIVE", "SUPERSEDED", "RESCINDED")
ALLOCATION_VARIANTS = ("PROVISIONAL", "FINAL")

# ---------------------------------------------------------------- permit (§3.4)
LIMIT_STATUSES = ("DRAFT_LIMITS", "INTERIM", "FINAL")
COMPLIANCE_STATUSES = (
    "NOT_REPORTED",
    "IN_COMPLIANCE",
    "SHORTFALL",
    "RESOLVED",
    "VIOLATION",
)
SCHEDULE_TIERS = ("TIER_A", "TIER_B", "TIER_C")

# ------------------------------------------------------- practice project (§3.6)
PRACTICE_TYPES = (
    "COVER_CROP",
    "RIPARIAN_BUFFER",
    "NUTRIENT_MANAGEMENT",
    "WETLAND_RESTORATION",
)
PROJECT_STATUSES = (
    "REGISTERED",
    "BASELINE_VERIFIED",
    "IMPLEMENTED",
    "CERTIFIED",
    "PENDING_REVERIFICATION",
    "REVOKED",
)
LIVE_PROJECT_STATUSES = (
    "REGISTERED",
    "BASELINE_VERIFIED",
    "IMPLEMENTED",
    "CERTIFIED",
    "PENDING_REVERIFICATION",
)

# ----------------------------------------------------- verification event (§3.6)
EVENT_TYPES = ("BASELINE", "IMPLEMENTATION", "REVERIFICATION")
EVENT_OUTCOMES = ("PASS", "PARTIAL", "FAIL")

# ---------------------------------------------------------- credit batch (§3.7)
BATCH_STATUSES = ("ISSUED", "LISTED", "RETIRED", "INVALIDATED")

# ----------------------------------------------------- credit transaction (§3.8)
TRANSACTION_STATUSES = ("PROPOSED", "APPROVED", "VOIDED")
VOID_REASONS = ("REGISTRY_ACTION", "ADAPTIVE_HOLD", "BATCH_INVALIDATED")

# -------------------------------------------------------- adaptive review (§3.9)
REVIEW_STATUSES = ("OPEN", "FINALIZED")
REVIEW_VERDICTS = ("ON_TRACK", "OFF_TRACK", "INDETERMINATE")

# Resources that carry only `id` and `created_at` (§2.4) — no updated_at, no version.
APPEND_ONLY_RESOURCES = ("MonitoringSample", "VerificationEvent")
