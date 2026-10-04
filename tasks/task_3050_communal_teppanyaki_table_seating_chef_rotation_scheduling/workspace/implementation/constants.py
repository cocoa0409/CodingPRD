"""Pinned constants from SCAFFOLD.yaml §1.3 and the PRD narrative."""

# --- Roles (§1.7) -----------------------------------------------------------
ROLES = ["PlatformAdmin", "FloorManager", "Host", "Chef", "SushiChef"]
ENTITY_BACKED_ROLES = {"Chef": "chefs", "SushiChef": "chefs"}

# --- Settlement (§1.3) ------------------------------------------------------
GUESTS_BILLED_CAP = 3
COMPLIMENT_CREDIT_CENTS = 500
CELEBRATION_FEE_CENTS = 900
CELEBRATION_TIER_MULTIPLIER = {
    "NONE": 0.0,
    "BIRTHDAY": 1.0,
    "ANNIVERSARY": 1.0,
    "GRADUATION": 1.2,
    "CORPORATE": 1.5,
}

# --- Protein cost -----------------------------------------------------------
PROTEIN_COST_CENTS_PER_GRAM = 4.0
PROTEIN_GRAM_COST_CONTROL_PCT = 0.05

# --- Table minimum true-up --------------------------------------------------
SHORTFALL_BAND_1_CENTS = 1000
SHORTFALL_BAND_2_CENTS = 2000
SHORTFALL_FACTOR_BAND_1 = 0.50
SHORTFALL_FACTOR_BAND_2 = 0.60
SHORTFALL_FACTOR_BAND_3 = 0.75
TABLE_MINIMUM_TRUEUP_ROUND_INCREMENT_CENTS = 25

# --- Seat surcharge ---------------------------------------------------------
SURCHARGE_ROUNDING_INCREMENT_CENTS = 25

# --- Credit application -----------------------------------------------------
CREDIT_CAP_CENTS = 2500
CREDIT_CAP_PCT = 0.12
CREDIT_ELIGIBLE_TIERS = ["GOLD", "PLATINUM"]
CREDIT_MIN_AMOUNT_CENTS = 500

# --- Chef rotation ----------------------------------------------------------
MIN_CHEF_RESET_MINUTES = 3
SHORT_TABLE_BONUS = 80
SHORT_TABLE_TIERS = ["T2", "T4"]

# --- Protein portion standard ----------------------------------------------
PROTEIN_PORTS_PER_GUEST = 1
GUEST_PORT_SHARE_DIVISOR = 4
PROTEIN_GRAM_PORT_SIZE = 30
PROTEIN_VARIANCE_CAP_GRAMS = 40

# --- Sushi plating ----------------------------------------------------------
SUSHI_ADVANCE_MINUTES = 6
GRILL_START_LEAD_MINUTES = 9
SUSHI_LEAD_DIVISOR = 3
LATE_GRILL_THRESHOLD_MINUTES = 6
LATE_EARLY_GRILL_DEBT_MINUTES = 3
SUSHI_PLATE_LATENESS_MINUTES = 8

# --- Course timing ----------------------------------------------------------
HOURLY_TRIGGER_MINUTE = 35
EARLY_GRILL_TOLERANCE_MINUTES = 10
LATE_EARLY_CHEF_DEBT_MINUTES = 2
SHOW_UNDERRUN_TOLERANCE_MINUTES = 4
PLANNED_EARLY_MINUTE = 6

# --- Turn-over window -------------------------------------------------------
GRID_SNAP_MINUTES = 5
TURN_DEBT_BUCKET_WIDTH_MINUTES = 5

# --- Turn debt --------------------------------------------------------------
BURST_TURN_DEBT_FACTOR_PCT = 150
SHORTFALL_CAPACITY_MINUTES = 480
SHORTFALL_LETTER_COUNT = 20
SHORTFALL_BUCKET_MINUTES = [3, 3, 4, 4, 5, 5, 6, 6, 7, 7,
                            8, 8, 9, 9, 10, 10, 11, 11, 12, 12]
TURN_DEBT_ESCALATION_THRESHOLD = 60
MAX_TURN_DEBT_ADD_MINUTES = 40

# --- Restaurant charge ------------------------------------------------------
ASSIGNMENT_FEE_CENTS = 299
ASSIGNABLE_GUEST_CAP = 12
ASSIGNMENT_FEE_MULTIPLIER = {"LOW": 0.90, "MEDIUM": 1.00, "HIGH": 1.20}

# --- Venue cost report ------------------------------------------------------
ROUNDING_INCREMENT_CENTS = 100
READY_TIER_CODES = ["T2", "T4", "T6", "T8"]

# --- Sushi plate dwell ------------------------------------------------------
PLATE_DWELL_MINUTES = 5
SUSHI_COUNTER_SEAT_CAPACITY = 1
RESTAGE_PLATE_MINUTES = 5

# --- Booking / hold lifecycle ----------------------------------------------
BOOKING_HORIZON_MINUTES = 20160
HOLD_WINDOW_MINUTES = 20
HOLD_MAX_COUNT = 3
NO_SHOW_GRACE_MINUTES = 15
NO_SHOW_RESTRICTION_COUNT = 2
PRIOR_HOLD_GRACE_MINUTES = 60
MAINTENANCE_LATE_GRACE_MINUTES = 30
GRILL_REBUILD_MINUTES = 120
FILTER_SERVICE_THRESHOLD_DEFAULT = 40

# --- Enums ------------------------------------------------------------------
VENUE_STATUSES = ["ACTIVE", "VENTILATION_HOLD"]
PARTY_STATUSES = ["ACTIVE", "RESTRICTED"]
LOYALTY_TIERS = ["NONE", "SILVER", "GOLD", "PLATINUM"]
TIER_CODES = ["T2", "T4", "T6", "T8", "T10"]
TIER_STATUSES = ["ACTIVE", "RETIRED"]
TABLE_STATUSES = ["AVAILABLE", "SEATED", "TURNING", "MAINTENANCE"]
RESERVATION_STATUSES = ["DRAFT", "REQUESTED", "HELD", "SEATED",
                        "CLOSED", "NO_SHOW", "ABANDONED"]
CELEBRATIONS = ["NONE", "BIRTHDAY", "ANNIVERSARY", "GRADUATION", "CORPORATE"]
PAYMENT_MODES = ["CARD_ONLY", "CARD_THEN_CREDIT", "CREDIT_ONLY"]
SEATING_STATUSES = ["ACTIVE", "VACATED"]
CHEF_STATUSES = ["OFF_SHIFT", "ON_STATION", "CLEARING"]
SHOW_PHASES = ["SUSHI", "GRILL", "DESSERT", "CELEBRATION"]
SHOW_STATUSES = ["PLANNED", "STARTED", "FINISHED", "SKIPPED"]
WINDOW_KINDS = ["VENTILATION_SERVICE", "GRILL_REBUILD", "HOOD_DEEP_CLEAN"]
WINDOW_STATUSES = ["SCHEDULED", "ACTIVE", "COMPLETED"]
SUSHI_PREP_PHASES = ["RAW_CUT", "ROLLED", "PLATED"]
SUSHI_STATUSES = ["OPEN", "VOIDED"]
LEDGER_KINDS = ["SEAT_SURCHARGE", "CELEBRATION_CHARGE", "TABLE_MINIMUM_TRUEUP"]
LEDGER_STATUSES = ["POSTED", "VOIDED"]
PROTEIN_STATUSES = ["POSTED", "VOIDED"]
ZONES = ["ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"]