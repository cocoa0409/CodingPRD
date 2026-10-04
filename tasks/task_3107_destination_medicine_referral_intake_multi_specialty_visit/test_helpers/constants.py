"""Domain thresholds and test defaults — numeric constants from the PRD."""

CLOCK_START = "2026-09-01T00:00:00Z"
SLOT_DATE = "2026-09-10"

THRESHOLDS = {
    # deposit tiers (PRD §3.5)
    "TIER_HIGH_FLOOR_CENTS": 500000,
    "TIER_MID_FLOOR_CENTS": 100000,
    "RATE_HIGH": 0.30,
    "RATE_MID": 0.20,
    "RATE_LOW": 0.10,
    "BASE_VISIT_CENTS": 150000,
    # estimate tiers (PRD §3.5)
    "DISCOUNT_TIER_3": 0.05,
    "DISCOUNT_TIER_4": 0.10,
    "INTERNATIONAL_MULTIPLIER": 1.20,
    # itinerary window (PRD §3.7)
    "MAX_WINDOW_DAYS": 5,
    # fatigue (PRD §3.3)
    "VERIFY_INCREMENT": 2,
    "REMOTE_CONSULT_DECREMENT": 3,
    "WITHDRAWAL_THRESHOLD": 10,
    # deposit deadline (PRD §3.6)
    "DEPOSIT_DEADLINE_DAYS": 14,
    # fatigue review-day guard (PRD §3.3)
    "MAX_REVIEW_DAYS": 3,
}

# Standard service windows used throughout the fixtures.
WINDOW_START_MIN = 480
WINDOW_END_MIN = 1020

# Standard operator identifiers per role (opaque, per PRD §2.1).
OP_IC = "ic-anna"
OP_IC_B = "ic-drew"
OP_CR = "cr-boris"
OP_FC = "fc-cora"
OP_LC = "lc-erin"
OP_ADMIN = "admin-pat"

# Canonical deposit for a 2-specialty care team: 2 * 150000 = 300000 -> 20% tier.
DEPOSIT_TWO_SPECIALTY_CENTS = 60000
# Canonical deposit for a 4-specialty care team: 4 * 150000 = 600000 -> 30% tier.
DEPOSIT_FOUR_SPECIALTY_CENTS = 180000
