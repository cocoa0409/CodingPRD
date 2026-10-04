# Named Constants Registry — values pinned to PRD.md / SCAFFOLD.yaml exactly.
from decimal import Decimal

DEFAULT_CLOCK_START_ISO = "2026-09-01T00:00:00Z"  # logical clock default at server boot
QUALIFY_MIN_AUDIT_SCORE = 70                       # PENDING_AUDIT -> QUALIFIED requires audit_score >= 70
REQUALIFY_MIN_AUDIT_SCORE = 80                     # SUSPENDED -> QUALIFIED requires audit_score >= 80
OVERRECEIPT_TOLERANCE_PCT = 110                    # cumulative non-REJECTED lot kg <= committed_volume_kg * 110%
FREIGHT_ESTIMATE_CENTS_PER_KG = 40                 # provisional landed cost freight add-on
KG_PER_CASE = 10                                   # finished-goods case weight
ISOLATE_KG_PER_FINISHED_KG_PCT = 85                # required_isolate_kg = ceil(actual_quantity_kg * 0.85)
EXTRUSION_PROCESSING_MARKUP_PCT = 35               # product cost = weighted lot cost * 1.35 + packaging
PACKAGING_CENTS_PER_KG = 110
ANIMAL_PROTEIN_REFERENCE_CENTS_PER_KG = 920        # price-parity denominator
PARITY_GOAL_MAX = Decimal("1.05")                  # parity_goal_met when price_parity_index <= 1.05
LAUNCH_MIN_ATTAINMENT_PCT = Decimal("85.00")       # LTO CONVERTED requires attainment_pct >= 85.00
SAMPLING_MIN_REDEMPTION_PCT = Decimal("12.00")     # SAMPLING CONVERTED requires redemption_rate_pct >= 12.00
FORECAST_MISS_THRESHOLD_PCT = Decimal("20.00")     # is_miss when variance_pct <= -20.00
TEXTURE_EQUIVALENCE_MIN_SCORE = 80                 # audit passes when texture_score >= 80
MOISTURE_VARIANCE_MAX_PCT = Decimal("3.0")         # audit passes when moisture_variance_pct <= 3.0
CLAIM_HIGH_PROTEIN_MIN_PROTEIN_G = 20              # HIGH_PROTEIN claim requires protein_g >= 20
CLAIM_LOW_SAT_FAT_MAX_FAT_G = 3                    # LOW_SATURATED_FAT claim requires fat_g <= 3
SHELF_LIFE_DAYS_FOODSERVICE = 45
SHELF_LIFE_DAYS_RETAIL_REFRIGERATED = 60
SHELF_LIFE_DAYS_RETAIL_FROZEN = 270
SHELF_LIFE_DAYS_SAMPLES = 30
MIN_PROGRAM_GAP_DAYS = 14                          # same-partner LTO windows need >= 14 day gap
EXPIRY_RISK_WINDOW_DAYS = 15                       # EXPIRY_RISK write-down requires <= 15 days to expiry (or past)
NRV_CENTS_PER_CASE_FOODSERVICE = 1000
NRV_CENTS_PER_CASE_RETAIL_REFRIGERATED = 1200
NRV_CENTS_PER_CASE_RETAIL_FROZEN = 1500
NRV_CENTS_PER_CASE_SAMPLES = 0

SHELF_LIFE_DAYS = {
    "FOODSERVICE": SHELF_LIFE_DAYS_FOODSERVICE,
    "RETAIL_REFRIGERATED": SHELF_LIFE_DAYS_RETAIL_REFRIGERATED,
    "RETAIL_FROZEN": SHELF_LIFE_DAYS_RETAIL_FROZEN,
    "SAMPLES": SHELF_LIFE_DAYS_SAMPLES,
}

NRV_CENTS_PER_CASE = {
    "FOODSERVICE": NRV_CENTS_PER_CASE_FOODSERVICE,
    "RETAIL_REFRIGERATED": NRV_CENTS_PER_CASE_RETAIL_REFRIGERATED,
    "RETAIL_FROZEN": NRV_CENTS_PER_CASE_RETAIL_FROZEN,
    "SAMPLES": NRV_CENTS_PER_CASE_SAMPLES,
}

ISOLATE_TYPES = ["PEA", "FABA_BEAN", "SOY", "MUNG_BEAN"]
CHANNELS = ["FOODSERVICE", "RETAIL_REFRIGERATED", "RETAIL_FROZEN", "SAMPLES"]
SITE_TYPES = ["OWNED", "CO_MAN"]
PROGRAM_TYPES = ["FOODSERVICE_LTO", "SAMPLING_DEMO"]
CLAIM_TYPES = ["HIGH_PROTEIN", "LOW_SATURATED_FAT", "GLUTEN_FREE", "NON_GMO"]
WRITEDOWN_REASONS = ["FORECAST_MISS", "EXPIRY_RISK", "RECALL"]

ROLES = [
    "PlatformAdmin",
    "ProcurementManager",
    "QualityManager",
    "PlantManager",
    "ProductManager",
    "ChannelManager",
    "DemandPlanner",
    "FinanceController",
]

# Channel <-> program_type mapping (FOODSERVICE_LTO = FOODSERVICE, SAMPLING_DEMO = SAMPLES)
PROGRAM_CHANNEL_MAP = {
    "FOODSERVICE_LTO": "FOODSERVICE",
    "SAMPLING_DEMO": "SAMPLES",
}
