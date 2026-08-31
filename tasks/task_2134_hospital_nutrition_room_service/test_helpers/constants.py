"""Numeric constants the PRD pins for the nutrition domain."""

# --- Logical clock (PRD 2.4) ------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Ordinal ladders (PRD 3.4) ----------------------------------------------
TEXTURE_ORDINAL = {"REGULAR": 0, "MINCED_MOIST": 1, "PUREED": 2, "LIQUIDISED": 3}
LIQUID_ORDINAL = {
    "THIN": 0,
    "MILDLY_THICK": 1,
    "MODERATELY_THICK": 2,
    "EXTREMELY_THICK": 3,
}

# --- Envelope / nil-per-os (PRD 3.4) ----------------------------------------
CLEAR_LIQUID_CARB_CAP_G = 15.0

# --- Tray cost (PRD 3.6) ----------------------------------------------------
WASTE_FACTOR = 1.08
TEXTURE_PREP_SURCHARGE_CENTS = {
    "REGULAR": 0,
    "MINCED_MOIST": 25,
    "PUREED": 60,
    "LIQUIDISED": 90,
}

# --- Period cost rollup (PRD 3.5) -------------------------------------------
TIER_A_MAX_EXCLUSIVE = 2000
TIER_B_MAX_EXCLUSIVE = 6000
OVERHEAD_RATE = {"A": 0.180, "B": 0.150, "C": 0.120}
BULK_DISCOUNT_RATE = {"A": 0.000, "B": 0.020, "C": 0.045}

# --- Production forecast (PRD 3.5) ------------------------------------------
ROLLING_HISTORY_DEPTH = 3
NO_SHOW_ADJUSTMENT = 0.92
PARTICIPATION_RATE = 0.85
AVERAGE_TRAY_COST_CENTS = 1150

# --- Tray service compliance (PRD 3.7) --------------------------------------
HOT_MIN_CELSIUS = 60.0
COLD_MAX_CELSIUS = 4.0
LATE_PENALTY = 25
EARLY_PENALTY = 10
TEMP_RETRY_PENALTY = 15
ACCURACY_RETRY_PENALTY = 20

# --- Malnutrition risk scoring (PRD 3.9) ------------------------------------
SCREENING_WEIGHTS = {"weight_loss": 0.50, "intake": 0.30, "bmi": 0.20}
COMPREHENSIVE_WEIGHTS = {
    "weight_loss": 0.35,
    "intake": 0.25,
    "bmi": 0.20,
    "albumin": 0.20,
}
RISK_TIER_MODERATE_MIN = 30
RISK_TIER_HIGH_MIN = 60

# --- Satisfaction survey (PRD 3.9) ------------------------------------------
TASTE_WEIGHT = 0.40
TEMPERATURE_WEIGHT = 0.35
ACCURACY_WEIGHT = 0.25

# --- Escalation, SLA and revision bounds (PRD 3.3 / 3.8 / 3.9) --------------
MISSED_MEAL_CONSULT_THRESHOLD = 2
CONSULT_URGENT_SLA_HOURS = 4
CONSULT_ROUTINE_SLA_HOURS = 24
MAX_REVISION_ROUNDS = 3

# --- Pagination bounds (PRD 2.3) --------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
