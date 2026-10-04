"""Domain constants — every literal greppable against PRD.md.

Each block cites the PRD section the value comes from. Do not add a
constant here unless the PRD states the value verbatim.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "Before any operator sets it, the logical clock reads exactly
#  2026-09-01T00:00:00Z — a fixed server default, not the host's wall clock."
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Pagination (PRD §2.3) ---------------------------------------------------
# limit "defaults to 10 when omitted, with a minimum of 1 and a maximum of
# 100"; offset "defaults to 0".
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Fixed reference sets (PRD §2.9) -----------------------------------------
KNOWN_COMMODITIES = ("CORN", "SOYBEAN", "WHEAT", "APPLE", "COTTON")
KNOWN_STATE_CODES = ("CA", "TX", "IA", "FL")

# --- Use-site field bounds (PRD §3.2) ----------------------------------------
# "max_application_rate_lbs_acre must be greater than zero and no more than
#  8.0 pounds per acre"
ABSOLUTE_RATE_CAP_LBS_ACRE = 8.0

# --- Application fees and review timelines (PRD §3.2) ------------------------
# "500,000 cents for FOOD_USE, 150,000 cents for NON_FOOD_USE, and 500,000
#  cents for MIXED_USE"
APPLICATION_FEE_CENTS = {
    "FOOD_USE": 500000,
    "NON_FOOD_USE": 150000,
    "MIXED_USE": 500000,
}
# "540 days for FOOD_USE, 270 days for NON_FOOD_USE, and 540 days for
#  MIXED_USE"
APPLICATION_REVIEW_DAYS = {
    "FOOD_USE": 540,
    "NON_FOOD_USE": 270,
    "MIXED_USE": 540,
}
# "FOOD_USE and MIXED_USE each require EFFICACY, TOXICOLOGY,
#  ENVIRONMENTAL_FATE, and RESIDUE_CHEMISTRY, while NON_FOOD_USE requires
#  EFFICACY, TOXICOLOGY, and ENVIRONMENTAL_FATE."
REQUIRED_STUDY_TYPES = {
    "FOOD_USE": ("EFFICACY", "TOXICOLOGY", "ENVIRONMENTAL_FATE", "RESIDUE_CHEMISTRY"),
    "MIXED_USE": ("EFFICACY", "TOXICOLOGY", "ENVIRONMENTAL_FATE", "RESIDUE_CHEMISTRY"),
    "NON_FOOD_USE": ("EFFICACY", "TOXICOLOGY", "ENVIRONMENTAL_FATE"),
}

# --- Dietary model (PRD §3.3) ------------------------------------------------
# "The daily consumption values, in grams per day, are: CORN 12.5,
#  SOYBEAN 8.0, WHEAT 20.0, APPLE 15.0, and COTTON 0.0."
CONSUMPTION_G_DAY = {
    "CORN": 12.5,
    "SOYBEAN": 8.0,
    "WHEAT": 20.0,
    "APPLE": 15.0,
    "COTTON": 0.0,
}
# "a 70-kilogram reference body weight"
BODY_WEIGHT_KG = 70
# "multiply by an exposure factor of 0.01 milligrams per day per pound per acre"
OCC_EXPOSURE_FACTOR = 0.01
# "0.05 for GROUND, 0.15 for AERIAL, 0.10 for CHEMIGATION, and 0.02 for
#  SEED_TREATMENT"
RUNOFF_FACTOR = {
    "GROUND": 0.05,
    "AERIAL": 0.15,
    "CHEMIGATION": 0.10,
    "SEED_TREATMENT": 0.02,
}
# "true when the stored, rounded dietary_rq is at least 1.0, or the stored,
#  rounded occupational_rq is at least 1.0, or the stored, rounded
#  ecological_rq is at least 0.5"
LOC_DIETARY = 1.0
LOC_OCCUPATIONAL = 1.0
LOC_ECOLOGICAL = 0.5

# --- Signal words and registration numbers (PRD §3.4) ------------------------
# "category I maps to DANGER_POISON, II maps to WARNING, and both III and IV
#  map to CAUTION"
SIGNAL_WORD_BY_TOX = {
    "I": "DANGER_POISON",
    "II": "WARNING",
    "III": "CAUTION",
    "IV": "CAUTION",
}
# "the literal prefix EPA-RR- followed by a zero-padded six-digit sequence"
EPA_REGISTRATION_NUMBER_PREFIX = "EPA-RR-"
EPA_REGISTRATION_NUMBER_DIGITS = 6

# --- Amendment review timeline (PRD §3.5) ------------------------------------
# "The base is 365 days for a NEW_USE, 180 days for a RATE_CHANGE, and 91
#  days for a METHOD_CHANGE."
AMENDMENT_BASE_DAYS = {
    "NEW_USE": 365,
    "RATE_CHANGE": 180,
    "METHOD_CHANGE": 91,
}
# "90 days when the product's classification is RESTRICTED_USE; 180 days
#  when a NEW_USE payload includes tolerance_ppm ...; and 60 days when any
#  endangered-species bulletin of the product is IN_EFFECT."
RUP_ADDER_DAYS = 90
NEW_FOOD_USE_ADDER_DAYS = 180
BULLETIN_ADDER_DAYS = 60

# --- Registration review cycle (PRD §3.4 / §3.7) -----------------------------
# "opened_at exactly 5,475 days — fifteen years — after the approval instant
#  and due_at 180 days after it opens" (same values for the next cycle).
REVIEW_CYCLE_DAYS = 5475
REVIEW_COMPLETION_DAYS = 180

# --- Existing-stocks deadlines (PRD §3.8) ------------------------------------
# "Under FIXED, ... allow_sale_until is 365 days after effective_at, and
#  allow_use_until is 730 days after."
FIXED_SALE_DAYS = 365
FIXED_USE_DAYS = 730
# "Under DEPLETION, the sale window in days is the authorized units divided
#  by the declared monthly depletion rate, multiplied by thirty, and rounded
#  up to a whole number of days"
DEPLETION_DAYS_PER_MONTH = 30

# --- State registration fees and renewal (PRD §3.9) --------------------------
# "40,000 cents for CA, 25,000 for TX, 18,000 for IA, and 30,000 for FL"
STATE_BASE_FEE_CENTS = {
    "CA": 40000,
    "TX": 25000,
    "IA": 18000,
    "FL": 30000,
}
# "plus a restricted-use surcharge of 10,000 cents when the product is
#  RESTRICTED_USE at grant time"
RUP_SURCHARGE_CENTS = 10000
# "sets renewal_due_at 365 days out" / "advances by exactly 365 days from
#  its previous value"
RENEWAL_PERIOD_DAYS = 365
# "the instant exactly thirty days after its renewal_due_at is strictly
#  earlier than the new time" (lapse grace, PRD §2.4 step 4)
RENEWAL_GRACE_DAYS = 30
# "the whole days between renewal_due_at and the clock, divided by thirty
#  and rounded down, plus one"
DAYS_PER_OVERDUE_MONTH = 30
# "The late penalty is ten percent of that subtotal per month overdue,
#  rounded half-up to a whole cent."
LATE_MONTHLY_RATE = 0.10
