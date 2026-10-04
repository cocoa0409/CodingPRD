"""PRD-pinned constants (verbatim values from SCAFFOLD.yaml / PRD.md)."""
from decimal import Decimal

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

MAX_DISCOUNT_PCT = Decimal("0.40")
MIN_MONTHLY_MINIMUM_CENTS = 50000
SHORTFALL_BILLING_RATE = Decimal("0.80")
SHORTFALL_BREACH_THRESHOLD_CENTS = 250000
RENEGOTIATION_CASELOAD_DELTA_PCT = Decimal("0.30")
PROFICIENCY_TOLERANCE_PCT = Decimal("0.05")
QC_VALIDITY_DAYS = 30
UPTIME_WINDOW_DAYS = 90
UPTIME_WINDOW_HOURS = 2160
UPTIME_BREACH_THRESHOLD_PCT = Decimal("0.985")
CALIBRATION_FREE_HOURS_PER_YEAR = 16
UPTIME_SERVICE_CREDIT_CENTS = 25000
RESPONSE_SLA_HOURS = 24
ALLOWED_TERM_MONTHS = [24, 36, 48, 60]

PRICE_TABLE = {
    "VC300_CHEM_SLIDE":  {"family": "SLIDE",       "list_price_cents": 420},
    "VC300_LYTE_CART":   {"family": "CARTRIDGE",   "list_price_cents": 760},
    "VH500_CBC_CART":    {"family": "CARTRIDGE",   "list_price_cents": 890},
    "VH500_DIFF_SLIDE":  {"family": "SLIDE",       "list_price_cents": 385},
    "VU200_URINE_STRIP": {"family": "SLIDE",       "list_price_cents": 153},
    "QC_LEVEL_1":        {"family": "QC_MATERIAL", "list_price_cents": 3000},
    "QC_LEVEL_2":        {"family": "QC_MATERIAL", "list_price_cents": 3000},
    "CAL_KIT_STANDARD":  {"family": "CALIBRATOR",  "list_price_cents": 12500},
}

ROLES = [
    "PlatformAdmin",
    "FinanceReviewer",
    "ClinicManager",
    "FieldServiceEngineer",
    "LaboratoryTechnician",
]

MODELS = ["VETCHEM_300", "VETHEMAT_500", "VETURINE_200"]
PROGRAM_TYPES = ["PURCHASE", "LEASE", "REAGENT_COMMITMENT"]
