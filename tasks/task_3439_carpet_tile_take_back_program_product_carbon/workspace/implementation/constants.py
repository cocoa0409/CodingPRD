"""Program constants.

Every numeric/literal constant named by the PRD or SCAFFOLD is defined exactly
once here and referenced everywhere else. In particular the two constants the
PRD names but deliberately leaves unvalued (section 2.9 cascade C):

  TAKEBACK_LOT_CARBON_FACTOR  - carbon factor (kgCO2e/kg) of the feedstock lot
                                created by the take-back sort cascade.
  TAKEBACK_SUPPLIER_NAME      - supplier_name stamped on cascade-created lots;
                                supplier reliability groups on this exact string.
"""
from decimal import Decimal

# --- Canonical conversion / calculation constants (PRD 2.6, calc tables) ---
TILE_MASS_KG_PER_M2 = Decimal("4.0")
TRANSPORT_KGCO2E_PER_M2 = Decimal("0.35")
EOL_MAX_CREDIT_KGCO2E_PER_M2 = Decimal("2.10")

GRADE_RATE_CENTS_PER_M2 = {"A": 250, "B": 150, "C": 40}
PATHWAY_BONUS_CENTS_PER_KG = {
    "REUSE": 30,
    "DEPOLYMERIZE": 18,
    "DOWNCYCLE": 6,
    "LANDFILL": 0,
}
BONUS_CAP_FRACTION = Decimal("0.40")

BASE_PRICE_CENTS_PER_M2 = 1200
OTHER_LOT_FACTOR = Decimal("1.15")

CARBON_NEGATIVE_BUFFER_KGCO2E = Decimal("500.0")

# Contractor install-window buffer: one full day added at both ends (PRD 3.3).
CONTRACTOR_BUFFER_SECONDS = 86400

# --- PRD-named but deliberately unvalued constants (chosen here, once) ---
TAKEBACK_LOT_CARBON_FACTOR = Decimal("1.20")
TAKEBACK_SUPPLIER_NAME = "CarpetLoop Take-Back Program"

# --- Logical clock default (PRD 2.5) ---
DEFAULT_CLOCK_STR = "2026-09-01T00:00:00Z"

# --- Roles (PRD 2.1) ---
ROLES = (
    "PlatformAdmin",
    "SustainabilityManager",
    "Verifier",
    "ClaimsApprover",
    "Specifier",
    "Installer",
)
ALL_ROLES = frozenset(ROLES)

# --- Enum vocabularies (SCAFFOLD entity table) ---
BACKING_TYPES = ("STANDARD", "ADHESIVE_FREE_CAPABLE")
BOUNDARIES = ("CRADLE_TO_GATE", "CRADLE_TO_GRAVE")
CLAIM_INTENTS = ("NONE", "CARBON_NEUTRAL", "CARBON_NEGATIVE")
SOURCE_TYPES = (
    "RECLAIMED_FISHING_NET",
    "POST_CONSUMER_TILE",
    "POST_INDUSTRIAL_SCRAP",
    "VIRGIN",
)
INSTALLATION_SYSTEMS = ("ADHESIVE_FREE", "CONVENTIONAL")
ORDER_REASONS = ("WEAR", "DAMAGE", "DESIGN_CHANGE")
CONDITION_GRADES = ("A", "B", "C")
CLAIM_TYPES = ("CARBON_NEUTRAL", "CARBON_NEGATIVE")
REGISTRIES = ("VERRA", "GOLD_STANDARD", "ACR")
QC_OUTCOMES = ("PASS", "FAIL")
VERIFICATION_ACTIONS = ("ASSIGN", "CLEAR", "FAIL")
REVIEW_DECISIONS = ("APPROVE", "REJECT")
