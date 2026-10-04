"""Domain thresholds and pinned constants.

Every value below is stated in PRD.md prose; the PRD section is cited on each
entry so the constant can be re-derived from the contract alone.
"""

# --- Logical clock -----------------------------------------------------------
# PRD Section 2.5: "the logical clock is initialized to the fixed default
# instant 2026-09-01T00:00:00Z, and it must never fall back to wall-clock time".
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Barrier rank order -------------------------------------------------------
# PRD Section 2.6: "CONVENTIONAL is rank 1, MPF is rank 2, VF is rank 3, and
# GERM_FREE is rank 4, so that CONVENTIONAL < MPF < VF < GERM_FREE".
BARRIER_RANKS = {
    "CONVENTIONAL": 1,
    "MPF": 2,
    "VF": 3,
    "GERM_FREE": 4,
}
BARRIER_LEVELS_ORDERED = ["CONVENTIONAL", "MPF", "VF", "GERM_FREE"]

# --- Order intake (PRD Section 3.6) ------------------------------------------
# "Submission requires the delivery date to be at least 14 days after the
# current logical clock — the platform's minimum order lead time".
MIN_ORDER_LEAD_DAYS = 14
# "optionally a min_health_status floor defaulting to MPF".
DEFAULT_ORDER_MIN_HEALTH_STATUS = "MPF"

# --- Transport logistics (PRD Section 3.8) -----------------------------------
# "the difference between planned_arrival_date and departure_date must not
# exceed 48 hours — the platform's maximum transit duration".
MAX_TRANSIT_HOURS = 48
# "sanitized_at must lie within the 72 hours preceding departure".
SANITIZATION_WINDOW_HOURS = 72

# --- Colony availability forecast (PRD Section 3.2) --------------------------
# "the expected next-litter yield is the floor of breeding_pair_count
# multiplied by the strain's typical_litter_size multiplied by the survival
# rate 0.8".
SURVIVAL_RATE = 0.8
# "snp_panel_interval_weeks, the number of weeks allowed between
# genetic-monitoring panels, defaulting to 12".
DEFAULT_SNP_PANEL_INTERVAL_WEEKS = 12
# Colony generation_number default (PRD Section 3.2: "defaulting to 0").
DEFAULT_GENERATION_NUMBER = 0

# --- Order quote (PRD Section 3.6) -------------------------------------------
# "20 percent when the total quantity is at least 250 animals, otherwise
# 10 percent when it is at least 100 animals, otherwise no discount".
TIER1_QTY = 100
TIER1_DISCOUNT = 0.10
TIER2_QTY = 250
TIER2_DISCOUNT = 0.20
# "25 percent when the strain's immune_class is IMMUNOCOMPROMISED ... plus a
# barrier premium of 40 percent when the order's min_health_status is
# GERM_FREE, or 20 percent when it is VF, or nothing otherwise".
IMMUNO_SURCHARGE = 0.25
VF_PREMIUM = 0.20
GERM_FREE_PREMIUM = 0.40

# --- Shipment boxing (PRD Section 3.8) ---------------------------------------
# "10 per box when the average weight is below 15 grams (light animals),
# 4 per box when it is 25 grams or more (heavy animals), and 6 per box
# otherwise (standard animals)".
LIGHT_MAX_G = 15.0
HEAVY_MIN_G = 25.0
LIGHT_PER_BOX = 10
STANDARD_PER_BOX = 6
HEAVY_PER_BOX = 4

# --- Cage accounting (PRD Section 3.4) ---------------------------------------
# "the ceiling of that cohort's live headcount — count_male plus count_female —
# divided by the cage density of 5 animals per cage".
CAGE_DENSITY = 5

# --- Protocol quota (PRD Section 3.4) ----------------------------------------
# "founding a colony adds 2 animals per breeding pair to the protocol's
# cumulative usage".
ANIMALS_PER_BREEDING_PAIR = 2

# --- Cryopreservation viability floor (PRD Section 3.10) ---------------------
# "the outcome hinges on the viability floor of 70: a viability_pct of at
# least 70 completes the contract and stores the figure, while a value below
# 70 routes the contract to VALIDATION_FAILED instead".
VIABILITY_FLOOR_PCT = 70

# --- Cohort age derivation (PRD Section 3.3) ---------------------------------
# "flooring that difference to whole days (a day is 86400 seconds), then
# flooring the days to whole weeks (7 days per week)".
SECONDS_PER_DAY = 86400
DAYS_PER_WEEK = 7

# --- Credit positions (PRD Section 3.6) --------------------------------------
# GROSS: "sums quoted_total_cents over orders in SOURCING, BACKORDERED,
# ALLOCATED, SCHEDULED, SHIPPED, and DELIVERED".
GROSS_EXPOSURE_STATUSES = [
    "SOURCING",
    "BACKORDERED",
    "ALLOCATED",
    "SCHEDULED",
    "SHIPPED",
    "DELIVERED",
]
# NET_BILLED: "sums quoted_total_cents over the customer's orders in
# DELIVERED only".
NET_BILLED_STATUSES = ["DELIVERED"]

# --- Pagination (PRD Section 2.3) --------------------------------------------
# "The limit parameter defaults to 10 when omitted, and any supplied value must
# lie between 1 and 100 inclusive. The offset parameter defaults to 0".
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Facility suspension cascade reason (PRD Section 3.1) --------------------
# "in which case suspension_reason is set to the literal
# OVERDUE_CORRECTIVE_ACTION".
SUSPENSION_REASON_OVERDUE_CORRECTIVE_ACTION = "OVERDUE_CORRECTIVE_ACTION"

# --- Standard fixture instants ------------------------------------------------
# All derived from the logical-clock default so that every default payload is
# reachable without advancing the clock:
#   * cohort birth at the clock default (must not lie after the clock);
#   * required delivery 42 days out (>= 14-day minimum lead time);
#   * departure 24 h before arrival, transit 24 h (<= 48 h), arrival on or
#     before the required delivery date;
#   * sanitization 2 h before departure (within the 72 h window).
COHORT_BIRTH_DATE_ISO = "2026-09-01T00:00:00Z"
STANDARD_REQUIRED_DELIVERY_DATE_ISO = "2026-10-13T12:00:00Z"
STANDARD_DEPARTURE_DATE_ISO = "2026-10-12T08:00:00Z"
STANDARD_PLANNED_ARRIVAL_DATE_ISO = "2026-10-13T08:00:00Z"
STANDARD_SANITIZED_AT_ISO = "2026-10-12T06:00:00Z"
# Facility registration validity: strictly after the clock default.
STANDARD_REGISTRATION_EXPIRES_AT_ISO = "2027-09-01T00:00:00Z"
# Protocol approval window spanning the standard test horizon.
STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO = "2026-09-01T00:00:00Z"
STANDARD_PROTOCOL_EXPIRATION_DATE_ISO = "2029-09-01T00:00:00Z"
# Health-screen sampling instant (on the logical clock, after room creation).
STANDARD_SCREEN_SCHEDULED_AT_ISO = "2026-09-15T00:00:00Z"
# Inspection scheduling day (default open slot).
STANDARD_INSPECTION_DATE_ISO = "2026-09-05T00:00:00Z"


THRESHOLDS = {
    "MIN_ORDER_LEAD_DAYS": MIN_ORDER_LEAD_DAYS,
    "MAX_TRANSIT_HOURS": MAX_TRANSIT_HOURS,
    "SANITIZATION_WINDOW_HOURS": SANITIZATION_WINDOW_HOURS,
    "SURVIVAL_RATE": SURVIVAL_RATE,
    "TIER1_QTY": TIER1_QTY,
    "TIER1_DISCOUNT": TIER1_DISCOUNT,
    "TIER2_QTY": TIER2_QTY,
    "TIER2_DISCOUNT": TIER2_DISCOUNT,
    "IMMUNO_SURCHARGE": IMMUNO_SURCHARGE,
    "VF_PREMIUM": VF_PREMIUM,
    "GERM_FREE_PREMIUM": GERM_FREE_PREMIUM,
    "LIGHT_MAX_G": LIGHT_MAX_G,
    "HEAVY_MIN_G": HEAVY_MIN_G,
    "LIGHT_PER_BOX": LIGHT_PER_BOX,
    "STANDARD_PER_BOX": STANDARD_PER_BOX,
    "HEAVY_PER_BOX": HEAVY_PER_BOX,
    "CAGE_DENSITY": CAGE_DENSITY,
    "ANIMALS_PER_BREEDING_PAIR": ANIMALS_PER_BREEDING_PAIR,
    "VIABILITY_FLOOR_PCT": VIABILITY_FLOOR_PCT,
    "DEFAULT_SNP_PANEL_INTERVAL_WEEKS": DEFAULT_SNP_PANEL_INTERVAL_WEEKS,
}

TEST_DEFAULTS = {
    "CLOCK_DEFAULT_ISO": CLOCK_DEFAULT_ISO,
    "COHORT_BIRTH_DATE_ISO": COHORT_BIRTH_DATE_ISO,
    "STANDARD_REQUIRED_DELIVERY_DATE_ISO": STANDARD_REQUIRED_DELIVERY_DATE_ISO,
    "STANDARD_DEPARTURE_DATE_ISO": STANDARD_DEPARTURE_DATE_ISO,
    "STANDARD_PLANNED_ARRIVAL_DATE_ISO": STANDARD_PLANNED_ARRIVAL_DATE_ISO,
    "STANDARD_SANITIZED_AT_ISO": STANDARD_SANITIZED_AT_ISO,
    "STANDARD_REGISTRATION_EXPIRES_AT_ISO": STANDARD_REGISTRATION_EXPIRES_AT_ISO,
    "STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO": STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO,
    "STANDARD_PROTOCOL_EXPIRATION_DATE_ISO": STANDARD_PROTOCOL_EXPIRATION_DATE_ISO,
    "STANDARD_SCREEN_SCHEDULED_AT_ISO": STANDARD_SCREEN_SCHEDULED_AT_ISO,
    "STANDARD_INSPECTION_DATE_ISO": STANDARD_INSPECTION_DATE_ISO,
    "DEFAULT_ORDER_MIN_HEALTH_STATUS": DEFAULT_ORDER_MIN_HEALTH_STATUS,
    "PAGINATION_DEFAULT_LIMIT": PAGINATION_DEFAULT_LIMIT,
    "PAGINATION_MAX_LIMIT": PAGINATION_MAX_LIMIT,
}

__all__ = [
    "CLOCK_DEFAULT_ISO",
    "BARRIER_RANKS",
    "BARRIER_LEVELS_ORDERED",
    "MIN_ORDER_LEAD_DAYS",
    "DEFAULT_ORDER_MIN_HEALTH_STATUS",
    "MAX_TRANSIT_HOURS",
    "SANITIZATION_WINDOW_HOURS",
    "SURVIVAL_RATE",
    "DEFAULT_SNP_PANEL_INTERVAL_WEEKS",
    "DEFAULT_GENERATION_NUMBER",
    "TIER1_QTY",
    "TIER1_DISCOUNT",
    "TIER2_QTY",
    "TIER2_DISCOUNT",
    "IMMUNO_SURCHARGE",
    "VF_PREMIUM",
    "GERM_FREE_PREMIUM",
    "LIGHT_MAX_G",
    "HEAVY_MIN_G",
    "LIGHT_PER_BOX",
    "STANDARD_PER_BOX",
    "HEAVY_PER_BOX",
    "CAGE_DENSITY",
    "ANIMALS_PER_BREEDING_PAIR",
    "VIABILITY_FLOOR_PCT",
    "SECONDS_PER_DAY",
    "DAYS_PER_WEEK",
    "GROSS_EXPOSURE_STATUSES",
    "NET_BILLED_STATUSES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "SUSPENSION_REASON_OVERDUE_CORRECTIVE_ACTION",
    "COHORT_BIRTH_DATE_ISO",
    "STANDARD_REQUIRED_DELIVERY_DATE_ISO",
    "STANDARD_DEPARTURE_DATE_ISO",
    "STANDARD_PLANNED_ARRIVAL_DATE_ISO",
    "STANDARD_SANITIZED_AT_ISO",
    "STANDARD_REGISTRATION_EXPIRES_AT_ISO",
    "STANDARD_PROTOCOL_EFFECTIVE_DATE_ISO",
    "STANDARD_PROTOCOL_EXPIRATION_DATE_ISO",
    "STANDARD_SCREEN_SCHEDULED_AT_ISO",
    "STANDARD_INSPECTION_DATE_ISO",
    "THRESHOLDS",
    "TEST_DEFAULTS",
]
