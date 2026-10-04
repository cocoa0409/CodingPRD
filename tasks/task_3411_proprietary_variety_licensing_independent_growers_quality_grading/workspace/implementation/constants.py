"""All pinned constants from SCAFFOLD.yaml calculations / PRD. Defined exactly once."""
from decimal import Decimal

# --- cold_chain_evaluation ---
PRECOOL_MAX_HOURS = Decimal("8.0")
PULP_TEMP_COMPLIANT_MAX_C = Decimal("4.0")
PULP_TEMP_HARD_REJECT_C = Decimal("10.0")
COLD_CHAIN_BREACH_DEDUCTION_PCT = Decimal("0.08")

# --- expected_yield_and_booking ---
YIELD_KG_PER_PLANT = {
    "STRAWBERRY": Decimal("2.5"),
    "RASPBERRY": Decimal("1.8"),
    "BLACKBERRY": Decimal("2.0"),
    "BLUEBERRY": Decimal("3.0"),
}
DAYS_TO_FIRST_HARVEST = {
    "STRAWBERRY": 60,
    "RASPBERRY": 75,
    "BLACKBERRY": 90,
    "BLUEBERRY": 120,
}
WINDOW_OVERSUBSCRIBE_PCT = Decimal("1.20")

# --- royalty_charge ---
ROYALTY_BASE_CENTS_PER_PLANT = 45
TIER1_LIMIT = 100000
TIER1_RATE = 45
TIER2_LIMIT = 500000
TIER2_RATE = 38
TIER3_RATE = 30

# --- pool_rate ---
GRADE_WEIGHT = {
    "PREMIUM": Decimal("1.15"),
    "STANDARD": Decimal("1.00"),
    "PROCESS": Decimal("0.55"),
    "JUICE": Decimal("0.25"),
}
MARKETING_FEE_PCT = Decimal("0.06")
SHOULDER_WEEK_MULTIPLIER = Decimal("1.10")

# --- settlement_statement_net ---
DISPUTE_WINDOW_DAYS = 14

# --- recall_compensation ---
DEFAULT_COMPENSATION_PER_PLANT_CENTS = 22

# --- enums ---
BERRY_TYPES = ("STRAWBERRY", "RASPBERRY", "BLACKBERRY", "BLUEBERRY")
CULTURAL_PRACTICE_CODES = (
    "ORGANIC",
    "CONVENTIONAL",
    "DRIP_IRRIGATION",
    "INTEGRATED_PEST_MANAGEMENT",
    "SOIL_FUMIGATION_FREE",
)
ROLES = (
    "PlatformAdmin",
    "BreedingManager",
    "ComplianceOfficer",
    "NurseryManager",
    "GrowerPrincipal",
    "CoolingOperator",
    "QualityGrader",
    "SettlementOfficer",
)

# --- logical clock startup default (PRD section 2.4) ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- pagination defaults (response_envelope) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
