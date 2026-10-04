"""Domain thresholds — numeric constants from the PRD calculations."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Term arithmetic (PRD §3.2, §3.4).
TERM_DAYS = 365
GRACE_DAYS = 30
REINSTATEMENT_WINDOW_DAYS = 90
REFUND_WINDOW_DAYS = 30
CALL_EXPIRY_HOURS = 24

# Tow overage (PRD §3.7).
COURTESY_BONUS_MILES = 3

# Federation parts price book in cents (PRD §3.7).
PARTS_PRICE_BOOK_CENTS = {
    "BAT-G24": 14500,
    "BAT-G35": 16900,
    "TIRE-SPO": 9900,
    "FUEL-CAN": 1200,
    "LOCK-KIT": 0,
}

# Inter-club SCHEDULE flat amounts in cents, indexed [benefit_tier][service_type]
# (PRD §3.8).
TIER_FLAT_SCHEDULE_CENTS = {
    "CLASSIC": {"TOW": 8900, "BATTERY": 6200, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 12400},
    "PLUS": {"TOW": 12900, "BATTERY": 6800, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 13900},
    "PREMIER": {"TOW": 21500, "BATTERY": 7400, "LOCKOUT": 5500, "TIRE": 4800, "FUEL": 4100, "WINCH": 16800},
}

# Inter-club ACTUAL basis (PRD §3.8).
HOOK_FEE_CENTS = 5500
PER_MILE_CENTS = 240

# Federation assessment rate (PRD §3.8).
FEDERATION_ASSESSMENT_RATE = 0.045

# Household capacity (PRD §3.2).
MAX_ACTIVE_HOUSEHOLD_MEMBERS = 4
CHILD_MAX_AGE_EXCLUSIVE = 21

# Test-side identity strings for SoD scenarios (PRD §2.1: X-User-ID is opaque).
CLERK_1 = "clerk-1"
FIN_9 = "fin-9"
AGENT_1 = "agent-1"
