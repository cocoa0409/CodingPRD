"""Domain constants taken from the PRD's stated formulas and tables."""

# PRD §2.4 — "The server's logical clock starts at exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# PRD §3.1 — vine geometry.
SQ_FT_PER_ACRE = 43560

# PRD §3.4 — labor cost.
MIN_HOURLY_RATE = 16.50
STD_SHIFT_HOURS = 8.0
OVERTIME_MULTIPLIER = 1.5
BURDEN_RATE = 0.2850
MIN_CALL_IN_HOURS = 4.0
TRAVEL_BUFFER_MINUTES = 60

# PRD §3.3 — budget postures.
AT_RISK_FLOOR = 0.80
EXHAUSTED_FLOOR = 1.00

# PRD §3.5 — deficit irrigation.
DEFICIT_FACTOR = {"PREMIUM": 0.55, "STANDARD": 0.75, "BULK": 1.00}
AVAILABLE_WATER_FRACTION = 0.16
REFILL_SHARE = 0.50
MAX_SET_INCHES = 1.500

# PRD §3.6 — pest action thresholds.
ACTION_THRESHOLD_PCT = {
    "POWDERY_MILDEW": 5.0,
    "VINE_MEALYBUG": 2.0,
    "BOTRYTIS": 3.0,
    "LEAFHOPPER": 10.0,
}

# PRD §3.7 — yield estimation.
LB_PER_TON = 2000
G_PER_LB = 453.592
BERRY_GROWTH_RATE_PER_DAY = 0.004

# PRD §3.8 — delivery windows and the harvest ceiling.
NEARLY_FULL_FLOOR = 0.85
FULL_FLOOR = 1.00
HARVEST_TOLERANCE = 1.10

# PRD §3.9 — settlement.
TIER_1_FLOOR = 15000
TIER_2_FLOOR = 20000
PROVISIONAL_PASS_THROUGH_SHARE = 0.50

# PRD §3.3 — review loop cap.
MAX_REVISION_ROUNDS = 2

# Well-formed UUIDs that no server-minted resource will ever carry, for the
# not-found paths described in PRD §2.5.
MISSING_UUID_A = "11111111-1111-4111-8111-111111111111"
MISSING_UUID_B = "22222222-2222-4222-8222-222222222222"
MISSING_UUID_C = "33333333-3333-4333-8333-333333333333"
MISSING_UUID_D = "44444444-4444-4444-8444-444444444444"

# Reusable literal inputs shared across the suite.
TEST_DEFAULTS = {
    "VINEYARD_NAME": "Ridgecrest Ranch",
    "OWNER_LEGAL_NAME": "Ridgecrest Vineyards LLC",
    "AVA_REGION": "Paso Robles",
    "CLIENT_CONTACT_EMAIL": "ops@ridgecrest.example",
    "CLIENT_SIGNATURE_NAME": "Dana Ridgecrest",
    "WINERY_NAME": "Coastal Cellars",
}
