"""Business constants declared by the Digital Makeline Capacity API contract.

Every value here is a literal the contract states. Tests import these instead of
re-typing magic numbers, so a boundary case such as "exactly half of par" reads
as the rule it exercises.
"""

# ── Logical clock ──────────────────────────────────────────────────────────
# The clock starts at this instant on a fresh deployment and only moves when a
# PlatformAdmin sets it.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ── Roles ──────────────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_GENERAL_MANAGER = "GeneralManager"
ROLE_LINE_WORKER = "LineWorker"
ROLE_MARKETPLACE_CHANNEL = "MarketplaceChannel"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_STORE_MANAGER,
    ROLE_GENERAL_MANAGER,
    ROLE_LINE_WORKER,
    ROLE_MARKETPLACE_CHANNEL,
)

# ── Pagination ─────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Ordering channels and lines ────────────────────────────────────────────
CHANNEL_FIRST_PARTY_DIGITAL = "FIRST_PARTY_DIGITAL"
CHANNEL_IN_STORE = "IN_STORE"
CHANNEL_MARKETPLACE = "MARKETPLACE"

LINE_DIGITAL = "DIGITAL"
LINE_IN_STORE = "IN_STORE"

# ── Store throttle bands ───────────────────────────────────────────────────
THROTTLE_OPEN = "OPEN"
THROTTLE_THROTTLED = "THROTTLED"
THROTTLE_CLOSED = "CLOSED"

# ── Ingredient shortage bands ──────────────────────────────────────────────
SHORTAGE_STOCKED = "STOCKED"
SHORTAGE_LOW = "LOW"
SHORTAGE_DEPLETED = "DEPLETED"

# Fractions of par that bound the LOW and DEPLETED bands.
LOW_THRESHOLD_FRACTION = 0.5
DEPLETED_THRESHOLD_FRACTION = 0.25

# ── Menu item suppression states ───────────────────────────────────────────
SUPPRESSION_SELLABLE = "SELLABLE"
SUPPRESSION_SUPPRESSED_DIGITAL = "SUPPRESSED_DIGITAL"
SUPPRESSION_SUPPRESSED_MARKETPLACE = "SUPPRESSED_MARKETPLACE"
SUPPRESSION_SUPPRESSED_ALL = "SUPPRESSED_ALL"

SUPPRESSION_SCOPE_DIGITAL = "DIGITAL"
SUPPRESSION_SCOPE_MARKETPLACE = "MARKETPLACE"
SUPPRESSION_SCOPE_ALL = "ALL"

SUPPRESSION_CAUSE_SHORTAGE = "SHORTAGE"
SUPPRESSION_CAUSE_MANUAL = "MANUAL"
SUPPRESSION_CAUSE_RESTORED = "RESTORED"

# ── Batch statuses ─────────────────────────────────────────────────────────
BATCH_ACTIVE = "ACTIVE"
BATCH_DEPLETED = "DEPLETED"
BATCH_EXPIRED = "EXPIRED"
BATCH_WASTED = "WASTED"

WASTE_REASON_HOLD_TIME_EXPIRED = "HOLD_TIME_EXPIRED"
WASTE_REASON_CONTAMINATION = "CONTAMINATION"
WASTE_REASON_OVERPRODUCTION = "OVERPRODUCTION"

# ── Production window statuses ─────────────────────────────────────────────
WINDOW_OPEN = "OPEN"
WINDOW_CUTOFF = "CUTOFF"
WINDOW_SETTLED = "SETTLED"

# ── Order statuses ─────────────────────────────────────────────────────────
FULFILLMENT_PLACED = "PLACED"
FULFILLMENT_ACCEPTED = "ACCEPTED"
FULFILLMENT_IN_PRODUCTION = "IN_PRODUCTION"
FULFILLMENT_READY = "READY"
FULFILLMENT_PICKED_UP = "PICKED_UP"
FULFILLMENT_CANCELLED = "CANCELLED"
FULFILLMENT_EXPIRED = "EXPIRED"

PAYMENT_AUTHORIZED = "AUTHORIZED"
PAYMENT_CAPTURED = "CAPTURED"
PAYMENT_REFUNDED = "REFUNDED"
PAYMENT_VOIDED = "VOIDED"

ACCURACY_UNVERIFIED = "UNVERIFIED"
ACCURACY_VERIFIED = "VERIFIED"
ACCURACY_MISMATCHED = "MISMATCHED"

ACCURACY_CHECK_PENDING = "PENDING"
ACCURACY_CHECK_MATCHED = "MATCHED"
ACCURACY_CHECK_MISMATCHED = "MISMATCHED"

VERIFICATION_PASS = "PASS"
VERIFICATION_FAIL = "FAIL"

# ── Staffing deployment statuses ───────────────────────────────────────────
DEPLOYMENT_DRAFT = "DRAFT"
DEPLOYMENT_PUBLISHED = "PUBLISHED"
DEPLOYMENT_LOCKED = "LOCKED"
DEPLOYMENT_SUPERSEDED = "SUPERSEDED"

# ── Day close statuses ─────────────────────────────────────────────────────
DAY_CLOSE_OPEN = "OPEN"
DAY_CLOSE_CLOSED = "CLOSED"

# ── Timing rules ───────────────────────────────────────────────────────────
# A ready order expires once its promise time plus this many minutes passes.
PROMISE_EXPIRY_MINUTES = 45
# In-store orders are promised this many minutes after placement by default.
DEFAULT_INSTORE_PROMISE_MINUTES = 15
