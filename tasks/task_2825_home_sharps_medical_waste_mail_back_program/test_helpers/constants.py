"""Domain thresholds, catalogue rows and rates declared by the PRD."""

# --- Logical clock -----------------------------------------------------------
# PRD 2.4: before the first clock call the clock reads exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"

# --- Container size catalogue (PRD 3.4) -------------------------------------
# size_code -> (volume_liters, capacity_units, unit_cost_cents)
CONTAINER_CATALOG = {
    "ONE_QUART": (0.9, 100, 1450),
    "TWO_GALLON": (7.6, 800, 2600),
    "THREE_GALLON": (11.4, 1300, 3400),
    "EIGHT_GALLON": (30.3, 3600, 6900),
}

# --- Sizing rule (PRD 3.4) --------------------------------------------------
THERAPY_UNIT_FACTORS = {
    "INSULIN_PEN_NEEDLES": 1,
    "INSULIN_SYRINGES": 2,
    "AUTOINJECTOR_PENS": 6,
    "INFUSION_SETS": 9,
    "LANCETS_ONLY": 1,
}
SAFETY_MARGIN_NUMERATOR = 115
DAYS_PER_WEEK_DENOMINATOR = 700
INFUSION_SETS_MIN_VOLUME_LITERS = 7.6
LANCETS_ONLY_MAX_VOLUME_LITERS = 11.4

# --- Costing rates (PRD 3.4 / 3.8) -----------------------------------------
TRANSPORT_RATE_CENTS_PER_KG = 38
PROVISIONAL_GRAMS_PER_UNIT = 4
DESTRUCTION_RATE_CENTS_PER_UNIT = {
    "MANUFACTURER": 3,
    "HEALTH_PLAN": 2.5,
}
SURCHARGE_CENTS = {
    "RETURN_TO_PATIENT": 0,
    "ON_SITE_REPACK": 500,
    "DISPOSE_AS_RMW": 900,
}

# --- Rebate tiers (PRD 3.8) -------------------------------------------------
# (basis_low_inclusive, basis_high_inclusive, rebate_pct)
REBATE_TIERS = [
    (0, 14999, 0),
    (15000, 29999, 0.03),
    (30000, 100000000, 0.06),
]
ALLOWED_REBATE_PCTS = (0, 0.03, 0.06)

# --- Risk scoring (PRD 3.9) ------------------------------------------------
REASON_CODE_WEIGHTS = {
    "LOOSE_SHARPS_IN_BOX": 45,
    "UNAPPROVED_WASTE_TYPE": 40,
    "UNSEALED_CONTAINER": 30,
    "OVERFILLED_CONTAINER": 25,
    "WEIGHT_EXCEEDS_SPEC": 20,
    "MISSING_ABSORBENT": 15,
}
RISK_FULL_WEIGHT_MAX_AGE_DAYS = 90
RISK_HALF_WEIGHT_MAX_AGE_DAYS = 180
RISK_SUSPEND_THRESHOLD = 60
RISK_SCORE_CAP = 100
LATE_KIT_AUDIT_PENALTY = 10

# --- Label window (PRD 3.6) ------------------------------------------------
LABEL_VALIDITY_DAYS = 45
LABEL_VOID_QUARANTINE_HOURS = 24
TRACKING_PREFIXES = {
    "USPS_PARCEL_SELECT_MAILBACK": "USPSMB",
    "UPS_GROUND_MEDICAL": "UPSGM",
}
TRACKING_SEQUENCE_WIDTH = 8

# --- Certificates (PRD 3.8) ----------------------------------------------
CERTIFICATE_NUMBER_PREFIX = "CERT-"
CERTIFICATE_SEQUENCE_WIDTH = 5
FEDERAL_MINIMUM_RETENTION_YEARS = 3

# --- Kit lifecycle (PRD 3.4) ---------------------------------------------
SEAL_DEADLINE_GRACE_DAYS = 14

# --- State rule defaults (PRD 3.1) ---------------------------------------
DEFAULT_NOTIFICATION_DEADLINE_HOURS = 72

# --- Pagination (PRD 2.3) ------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
