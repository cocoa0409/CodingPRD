"""
Domain thresholds and pinned literals from the PRD.

Only values the PRD states in prose appear here; nothing is invented.
"""

from decimal import Decimal

# ─── Clock (PRD 2.5) ──────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD 2.3) ─────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Trial rollups (PRD 3.6) ──────────────────────────
MIN_VALID_REPS = 3
HA_PER_PLOT_FACTOR = 800

# ─── Management fee tiers (PRD 3.6) ───────────────────
MGMT_TIER_1_CEILING = Decimal("10000.00")
MGMT_TIER_2_CEILING = Decimal("50000.00")
MGMT_RATE_TIER_1 = Decimal("0.12")
MGMT_RATE_TIER_2 = Decimal("0.09")
MGMT_RATE_TIER_3 = Decimal("0.07")

# ─── Stability classification (PRD 3.7) ───────────────
STABLE_B_MIN = Decimal("0.80")
STABLE_B_MAX = Decimal("1.20")

# ─── Advancement index (PRD 3.8) ──────────────────────
YIELD_COMPONENT_CAP = Decimal("120")
QUALITY_MISS_PENALTY = 15
IMPUTED_COMPONENT_VALUE = Decimal("60")
STAGE_CONFIDENCE = {
    "NURSERY": Decimal("0.90"),
    "STAGE_1": Decimal("0.95"),
    "STAGE_2": Decimal("1.00"),
    "STAGE_3": Decimal("1.00"),
    "PRE_COMMERCIAL": Decimal("1.00"),
}

# ─── Site capacity posture (PRD 3.5) ──────────────────
RESTRICTED_RATIO = Decimal("0.85")
FROZEN_RATIO = Decimal("1.00")

# ─── Nursery (PRD 3.3) ────────────────────────────────
DEFAULT_FALLOW_BUFFER_DAYS = 14
MIN_ADVANCE_SEED_G = 250
WINTER_SOW_MONTHS = (10, 11, 12, 1, 2)
SUMMER_SOW_MONTHS = (4, 5, 6, 7, 8)

# ─── Seed increase (PRD 3.9) ──────────────────────────
BAG_SIZE_KG = 25
SEED_LOSS_PCT = Decimal("0.08")
FIELD_MULTIPLICATION_FACTOR = 40

# ─── Backcross recovery (PRD 3.4) ─────────────────────
MAS_BONUS_PCT = Decimal("2.5")
RECOVERY_CAP_PCT = Decimal("99.900")
CONVERSION_THRESHOLD_PCT = Decimal("99.0")
CONVERTED_TRAIT_SCORE = 8

# ─── Shared fixture vocabulary ────────────────────────
UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"

PROGRAM_PLOT_BUDGET = 5000
PROGRAM_BUDGET_USD = 2000000.00
OBJECTIVE_TARGET_YIELD = 11000.00
OBJECTIVE_BAR = 85.00
