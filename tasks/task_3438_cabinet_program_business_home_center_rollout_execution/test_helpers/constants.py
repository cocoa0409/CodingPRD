"""Domain constants for the Cabinet Program Rollout API test suite.

Every value below is stated in the PRD; the comment on each group names the
section that declares it. Tests import these instead of re-typing literals,
so a contract change is a one-line edit here.
"""

# ── Mounting and the logical clock (PRD §1 / §2.4) ──────────────────────────
API_PREFIX = "/cabinet"
# The clock endpoint is the sole route mounted OUTSIDE the API prefix.
CLOCK_ENDPOINT = "/_clock/set_current_utc"
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"   # reading before any administrative set
CURRENT_WEEK_DEFAULT = "2026-W36"        # ISO week containing CLOCK_DEFAULT

# ── Pagination (PRD §2.3) ───────────────────────────────────────────────────
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ── Pricing (PRD §3.3) ──────────────────────────────────────────────────────
TIER1_GROSS_CENTS = 500_000      # pre-discount gross >= this earns the 5% tier
TIER2_GROSS_CENTS = 2_000_000    # pre-discount gross >= this earns the 8% tier
TIER1_RATE = 0.05
TIER2_RATE = 0.08
CHANNEL_MULTIPLIER_STANDARD = 1.00
CHANNEL_MULTIPLIER_VOLUME = 0.95
CHANNEL_MULTIPLIER_NATIONAL = 0.90
CHANNEL_MULTIPLIERS = {
    "STANDARD": CHANNEL_MULTIPLIER_STANDARD,
    "VOLUME": CHANNEL_MULTIPLIER_VOLUME,
    "NATIONAL": CHANNEL_MULTIPLIER_NATIONAL,
}
PROGRAM_DISCOUNT_PCT_MIN = 0.0
PROGRAM_DISCOUNT_PCT_MAX = 0.5   # inclusive bound on program_discount_pct

# ── Delivery estimation (PRD §3.3 / §3.4) ───────────────────────────────────
EXTENDED_CLASS_EXTRA_WEEKS = 2   # EXTENDED lead_time_class adds 2 weeks
MAX_SLIP_WEEKS = 4               # strict selector's slip window length

# ── Capacity (PRD §3.4 / §3.5) ──────────────────────────────────────────────
EXPEDITE_OVERBOOK_PCT = 0.10     # expedite may exceed capacity by floor(cap x 0.10)

# ── Color match (PRD §3.5) ──────────────────────────────────────────────────
COLOR_MATCH_TOLERANCE = 2.0      # deltaE <= 2.0 passes; 2.0 exactly passes

# ── Design service (PRD §3.2) ───────────────────────────────────────────────
REVISION_CAP = 3                 # a 4th backward revision is rejected
DIFFERENT_STORE_BUFFER_MINUTES = 30   # travel buffer across different store codes

# ── Shipments and claims (PRD §3.5 / §3.6) ──────────────────────────────────
ATTEMPT_CAP = 3                  # the 3rd FAILED delivery auto-RETURNs the shipment
CLAIM_WINDOW_DAYS = 14           # filed_at <= delivered_at + 14 days (inclusive)
SETTLEMENT_CAP_MULT = 1.20       # settlement capped at 120% of list price
EARLY_FULL_DAYS = 7              # age <= 7 days settles at full value
LATE_FACTOR = 0.8                # older claims settle at 0.8 of base

# ── Program transition (PRD §3.7) ───────────────────────────────────────────
DISPLAY_RESET_DEADLINE_DAYS = 45  # transition start + 45 days
DISPOSITION_DEADLINE_DAYS = 90    # transition start + 90 days

# ── Credit hold boundary (PRD §2.8) ─────────────────────────────────────────
# An order moves onto CREDIT_HOLD iff open_exposure_cents is STRICTLY greater
# than credit_limit_cents; an exposure exactly equal to the limit passes, and
# held orders flip back to UNINVOICED whenever a recompute lands at or below.
CREDIT_HOLD_STRICTLY_GREATER = True

# ── Roles (PRD §2.1) ────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_RETAIL_DESIGNER = "RetailDesigner"
ROLE_DEALER_REP = "DealerRep"
ROLE_PLANT_SCHEDULER = "PlantScheduler"
ROLE_LOGISTICS_COORDINATOR = "LogisticsCoordinator"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"
ROLE_FIELD_SERVICE_REP = "FieldServiceRep"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_MANAGER,
    ROLE_RETAIL_DESIGNER,
    ROLE_DEALER_REP,
    ROLE_PLANT_SCHEDULER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_FIELD_SERVICE_REP,
)
