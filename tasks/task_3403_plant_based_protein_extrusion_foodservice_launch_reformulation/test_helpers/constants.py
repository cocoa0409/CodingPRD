"""Domain thresholds and pinned constants from PRD.md.

Every value below traces to a verbatim PRD statement; nothing here is invented.
Flat module-level names are the single source of truth; the lookup dicts are
derived from them (no duplicated literals).
"""

# --- Logical clock (PRD section 2.4) -----------------------------------------
# "the logical clock reads exactly 2026-09-01T00:00:00Z"
DEFAULT_CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Supplier qualification thresholds (PRD section 3.1) ---------------------
# "requires an audit_score of at least 70"
QUALIFY_MIN_AUDIT_SCORE = 70
# "the score must reach at least 80" (re-qualification out of SUSPENDED)
REQUALIFY_MIN_AUDIT_SCORE = 80

# --- Lot receipt / landed cost (PRD section 3.2) -----------------------------
# "would exceed 110 percent of the agreement's committed_volume_kg"
OVERRECEIPT_TOLERANCE_PCT = 110
# "a flat freight estimate of 40 cents per kilogram is added on top"
FREIGHT_ESTIMATE_CENTS_PER_KG = 40

# --- Production run costing (PRD section 3.5) --------------------------------
# "the actual output divided by 10 kilograms per case, rounded down"
KG_PER_CASE = 10
# "the actual output multiplied by 85 percent and rounded up to a whole kilogram"
ISOLATE_KG_PER_FINISHED_KG_PCT = 85

# --- Price parity (PRD section 3.4) ------------------------------------------
# "marked up by 35 percent for extrusion processing"
EXTRUSION_PROCESSING_MARKUP_PCT = 35
# "increased by 110 cents of packaging per kilogram"
PACKAGING_CENTS_PER_KG = 110
# "the animal-protein reference price of 920 cents per kilogram"
ANIMAL_PROTEIN_REFERENCE_CENTS_PER_KG = 920
# "parity_goal_met is true when the index is at most 1.05"
PARITY_GOAL_MAX = 1.05

# --- Program conversion gates (PRD section 3.6) ------------------------------
# "at least 85.00 percent attainment for an LTO"
LAUNCH_MIN_ATTAINMENT_PCT = 85.00
# "at least 12.00 percent redemption for a sampling program"
SAMPLING_MIN_REDEMPTION_PCT = 12.00
# "no other FOODSERVICE_LTO program with the same partner_code ... may sit
#  closer than 14 days away"
MIN_PROGRAM_GAP_DAYS = 14

# --- Forecast miss threshold (PRD section 3.8) -------------------------------
# "is_miss is true when that variance reaches negative 20.00 percent or worse"
FORECAST_MISS_THRESHOLD_PCT = 20.00

# --- Co-man equivalence audit (PRD section 3.3) ------------------------------
# "the texture score is at least 80"
TEXTURE_EQUIVALENCE_MIN_SCORE = 80
# "the moisture variance is at most 3.0 percent"
MOISTURE_VARIANCE_MAX_PCT = 3.0

# --- Label claim gates (PRD section 3.4) -------------------------------------
# "a HIGH_PROTEIN claim is supported only when protein_g is at least 20"
CLAIM_HIGH_PROTEIN_MIN_PROTEIN_G = 20
# "a LOW_SATURATED_FAT claim only when fat_g is at most 3"
CLAIM_LOW_SAT_FAT_MAX_FAT_G = 3

# --- Shelf life per channel (PRD section 3.7) --------------------------------
# "45 days for FOODSERVICE, 60 days for RETAIL_REFRIGERATED, 270 days for
#  RETAIL_FROZEN, and 30 days for SAMPLES"
SHELF_LIFE_DAYS_FOODSERVICE = 45
SHELF_LIFE_DAYS_RETAIL_REFRIGERATED = 60
SHELF_LIFE_DAYS_RETAIL_FROZEN = 270
SHELF_LIFE_DAYS_SAMPLES = 30

SHELF_LIFE_DAYS_BY_CHANNEL = {
    "FOODSERVICE": SHELF_LIFE_DAYS_FOODSERVICE,
    "RETAIL_REFRIGERATED": SHELF_LIFE_DAYS_RETAIL_REFRIGERATED,
    "RETAIL_FROZEN": SHELF_LIFE_DAYS_RETAIL_FROZEN,
    "SAMPLES": SHELF_LIFE_DAYS_SAMPLES,
}

# --- Write-down evidence window (PRD section 3.8) ----------------------------
# "EXPIRY_RISK requires the batch to be at most 15 days from expiry"
EXPIRY_RISK_WINDOW_DAYS = 15

# --- Net realizable value per case by channel (PRD section 3.8) --------------
# "1000 cents for FOODSERVICE, 1200 cents for RETAIL_REFRIGERATED, 1500 cents
#  for RETAIL_FROZEN, and 0 cents for SAMPLES"
NRV_CENTS_PER_CASE_FOODSERVICE = 1000
NRV_CENTS_PER_CASE_RETAIL_REFRIGERATED = 1200
NRV_CENTS_PER_CASE_RETAIL_FROZEN = 1500
NRV_CENTS_PER_CASE_SAMPLES = 0

NRV_CENTS_PER_CASE_BY_CHANNEL = {
    "FOODSERVICE": NRV_CENTS_PER_CASE_FOODSERVICE,
    "RETAIL_REFRIGERATED": NRV_CENTS_PER_CASE_RETAIL_REFRIGERATED,
    "RETAIL_FROZEN": NRV_CENTS_PER_CASE_RETAIL_FROZEN,
    "SAMPLES": NRV_CENTS_PER_CASE_SAMPLES,
}

# --- Channel-to-program-type mapping (PRD section 3.5) -----------------------
# "FOODSERVICE_LTO programs take FOODSERVICE runs and SAMPLING_DEMO programs
#  take SAMPLES runs"
CHANNEL_FOR_PROGRAM_TYPE = {
    "FOODSERVICE_LTO": "FOODSERVICE",
    "SAMPLING_DEMO": "SAMPLES",
}
