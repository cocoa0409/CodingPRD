"""Domain thresholds and numeric constants.

Every value below is pinned by PRD prose (section noted per group). Each
constant is defined exactly once; tests reference these names rather than
re-deriving literals.
"""

# --- Logical clock (PRD section 2.4) ---
# "Before any operator sets it, the logical clock reads exactly 2026-09-01T00:00:00Z."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
# Conventional post-boot clock used by fixtures before any domain writes.
CLOCK_BOOT_ISO = "2026-09-01T06:00:00Z"

# --- Corporate-gifting peak window (PRD section 2.9) ---
# Half-open [PEAK_WINDOW_START, PEAK_WINDOW_END).
PEAK_WINDOW_START = "2026-10-15T00:00:00Z"
PEAK_WINDOW_END = "2026-12-21T00:00:00Z"
PEAK_MULTIPLIER = 1.25

# --- Customization quote (PRD section 3.5) ---
COLOR_SURCHARGE_CENTS = 150        # per color beyond the first
PLACEMENT_SURCHARGE_CENTS = 200    # per placement beyond the first
SETUP_FEE_CENTS = 8000
SETUP_WAIVER_QTY = 144             # fee waived at quantity >= 144, both buyer types
# Quantity-tier discount, CORPORATE orders only:
TIER_QTY_22 = 500                  # quantity >= 500 -> 22% off
TIER_RATE_22 = 0.22
TIER_QTY_15 = 144                  # 144..499 -> 15% off
TIER_RATE_15 = 0.15
TIER_QTY_08 = 48                   # 48..143 -> 8% off
TIER_RATE_08 = 0.08

# --- Dealer allocation score (PRD section 3.4) ---
# STANDARD season: 0.50*sell_through + 0.30*brand + 2*tenure - 5*points
SCORE_W_STANDARD_SELL_THROUGH = 0.50
SCORE_W_STANDARD_BRAND = 0.30
SCORE_W_STANDARD_TENURE = 2
SCORE_W_STANDARD_INFRACTION = 5
# PEAK season: 0.35*sell_through + 0.45*brand + 2*tenure - 8*points
SCORE_W_PEAK_SELL_THROUGH = 0.35
SCORE_W_PEAK_BRAND = 0.45
SCORE_W_PEAK_TENURE = 2
SCORE_W_PEAK_INFRACTION = 8
# Distribution weight is max(allocation_score, 1).
ALLOCATION_MIN_WEIGHT = 1

# --- Infraction points and dealer standing (PRD section 3.2) ---
INFRACTION_POINTS = {
    "MAP_VIOLATION": 4,
    "UNAUTHORIZED_MARKETPLACE": 6,
    "BRAND_STANDARD": 3,
    "CHANNEL_DIVERSION": 5,
}
INFRACTION_EXPIRY_DAYS = 365
PROBATION_THRESHOLD = 8            # exactly 8 points is PROBATION
SUSPEND_THRESHOLD = 12             # exactly 12 points is SUSPENDED

# --- Print capacity ledger (PRD section 2.10) ---
PER_UNIT_MINUTES = {"LASER": 4, "PAD": 2}

# --- Cancellation fee and return window (PRD section 3.8) ---
CANCEL_FEE_RATE = 0.10             # 10% of final_quote_cents once art approved
RETURN_WINDOW_DAYS = 45

# --- Warranty fraud gate (PRD section 3.9) ---
FRAUD_PRIOR_THRESHOLD = 3          # >= 3 other non-DENIED claims in trailing 365 days

# --- Slot overlap and inspector scheduling (PRD sections 3.7, 3.1) ---
CHANGEOVER_BUFFER_MINUTES = 20     # cross-technology gap on the same station
TRAVEL_BUFFER_MINUTES = 60         # between consecutive inspections per inspector

# --- Dealer authorization (PRD section 3.1) ---
BRAND_PRESENTATION_MINIMUM = 70    # approval requires score >= 70
DEFAULT_CREDIT_LIMIT_CENTS = 500000
DEFAULT_DEALER_TIER = "STANDARD"

# --- Artwork proofing (PRD section 3.6) ---
MAX_PROOF_ROUNDS = 3

# --- Artwork declared/actual bounds (PRD sections 3.5, 3.6) ---
MIN_COLOR_COUNT = 1
MAX_COLOR_COUNT = 8
MIN_PLACEMENT_COUNT = 1
MAX_PLACEMENT_COUNT = 4

# --- Pagination (PRD section 2.3) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
