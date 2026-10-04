"""Domain thresholds — numeric constants named in the PRD.

Every value here is stated in PRD prose (§2.7, §2.8.1, §3) so tests can cite
the rule they assert against.
"""

CLOCK_START = "2026-09-01T00:00:00Z"

# --- Store / dwell -------------------------------------------------------
POSTURE_RESTRICTED_BAND_MINUTES = 30        # §2.7 "thirty minutes is the critical band"
DEFAULT_DWELL_CAPACITY_MINUTES = 60_000
DEFAULT_LOAD_BAYS_TOTAL = 4

# --- attraction_dwell_charge --------------------------------------------
DWELL_BAND_X3_MIN_PARTY = 10                # three when the party is ten or more
DWELL_BAND_X2_MIN_PARTY = 5                 # two when it is at least five but under ten
POND_CLINIC_PIN_THRESHOLD = 3               # POND_CLINIC under three is pinned to 1
DWELL_LONG_SLOT_MINUTES = 90                # surcharge past ninety minutes
DWELL_LONG_SLOT_SURCHARGE = 20

# --- Lane discipline -----------------------------------------------------
ARCHERY_LANE_CEILING = 12
SIMULATOR_LANE_CEILING = 6

# --- event_dwell_charge --------------------------------------------------
FREE_DEMO_DWELL_MINUTES = 15                # flat branch
EVENT_SEAT_BASE_MINUTES = 0.5               # half a minute per seat, first half
EVENT_SEAT_OVERFLOW_MULTIPLIER = 2.0

# --- boat_deal_contract_price -------------------------------------------
RIGGING_FEE_CENTS = 95_000
ACCESSORY_DISCOUNT_CAP_CENTS = 500_000
ACCESSORY_DISCOUNT_BPS_NEW = 500
ACCESSORY_DISCOUNT_BPS_USED = 250
TIER_CREDIT_BPS_BY_CARD_STATUS = {
    "NONE": 0,
    "PENDING": 100,
    "ACTIVE": 500,
    "SUSPENDED": 0,
}
FLOOR_PRICE_CENTS = 1

# --- deal_fee_and_tax_relay ---------------------------------------------
DOC_FEE_CENTS = 59_900
TITLE_FEE_BOAT_CENTS = 4_500
TITLE_FEE_OTHER_CENTS = 2_500
SALES_TAX_BPS = 725                         # 7.25%
DELIVERY_PREP_CENTS = 25_000

# --- deal_points_award ---------------------------------------------------
POINTS_BAND_BPS_LOW = 8
POINTS_BAND_BPS_MID = 12
POINTS_BAND_BPS_HIGH = 18
POINTS_BAND_LOW_MAX_CENTS = 5_000_000
POINTS_BAND_MID_MAX_CENTS = 15_000_000
POINTS_BPS_DENOMINATOR = 100_000
ACTIVE_CARD_MULTIPLIER = 2
POINTS_AWARD_CAP = 20_000

# --- trade_in_credit -----------------------------------------------------
ACTIVE_CARD_REBATE_BPS = 300                # three percent
PRIOR_TITLE_PENALTY_BPS = 200               # two percent
TOTAL_BPS_DENOMINATOR = 10_000

# --- permit_fee ----------------------------------------------------------
TIER_FEE_CENTS = {
    "FISHING": {"RESIDENT": 3200, "NON_RESIDENT": 8400, "SENIOR": 1500, "YOUTH": 800},
    "HUNTING": {"RESIDENT": 4500, "NON_RESIDENT": 12000, "SENIOR": 2200, "YOUTH": 900},
    "ARCHERY_RANGE": {"RESIDENT": 2100, "NON_RESIDENT": 3900, "SENIOR": 1100, "YOUTH": 600},
    "BOAT_REGISTRATION": {
        "RESIDENT": 6500,
        "NON_RESIDENT": 6500,
        "SENIOR": 6500,
        "YOUTH": 6500,
    },
}
TERM_BUCKET_STEP_BPS = {"LE_7": 10000, "LE_30": 12500, "LE_365": 10000, "GT_365": 15000}
LAND_ACCESS_UNIT_MICRO_CENTS = 125_000       # 12.5 cents per unit
MICRO_CENTS_PER_CENT = 10_000

# --- intake_project_charge ----------------------------------------------
INTAKE_BASE_CENTS = {"TAXIDERMY": 45_000, "OUTFITTING": 12_000, "BOAT_SERVICE": 8_000}
INTAKE_STAGE_UPLIFT_CENTS = {
    "INTAKE_QUOTED": 0,
    "PERMIT_VERIFIED": 0,
    "MATERIALS_ORDERED": 15_000,
    "CURING": 25_000,
    "READY_FOR_PICKUP": 25_000,
}
INTAKE_SPECIMEN_UPLIFT_CENTS = 3_500         # at or after CURING, per specimen
INTAKE_DEPOSIT_FLOOR_CENTS = 5_000
INTAKE_SPECIMEN_MAX_AT_CURING = 20
CURING_EXTENSION_DAYS = 21
INTAKE_ABANDON_DAYS = 90

# --- tier_threshold_eval -------------------------------------------------
TIER_THRESHOLD_SILVER = 8_000
TIER_THRESHOLD_GOLD = 25_000
TIER_THRESHOLD_PATRON = 60_000
TIER_RETAIN_POINTS = {"BASE": 0, "SILVER": 500, "GOLD": 1_500, "PATRON": 4_000}

# --- conservation_match_accrue ------------------------------------------
POINTS_PER_DOLLAR = 20                       # so one point is worth five cents
MATCH_ANNUAL_CAP_CENTS = 500
CENTS_PER_POINT = 5

# --- no_show_strike ------------------------------------------------------
STRIKE_LIMIT = 3
STRIKE_DECAY_QUARTER_DAYS = 90
STRIKE_DECAY_PER_QUARTER = 0.5
OVERRUN_STRIKE_THRESHOLD_MINUTES = 30

# --- club card -----------------------------------------------------------
CREDIT_LIMIT_FLOOR_CENTS = 50_000
CARD_PRODUCT_TIER_EXEMPT = "CLASSIC"

# --- loading dock / bay --------------------------------------------------
BAY_TURNOVER_BUFFER_MINUTES = 15

# --- events --------------------------------------------------------------
EVENT_CANCELLATION_POINTS = 250
EVENT_ATTENDANCE_POINTS = 100

# --- waiver --------------------------------------------------------------
DEFAULT_WAIVER_TERM_DAYS = 365

TEST_DEFAULTS = {
    "DWELL_CAPACITY_MINUTES": DEFAULT_DWELL_CAPACITY_MINUTES,
    "LOAD_BAYS_TOTAL": DEFAULT_LOAD_BAYS_TOTAL,
    "NEW_UNIT_HULL_CENTS": 9_000_000,
    "NEW_UNIT_MOTOR_CENTS": 1_800_000,
    "NEW_UNIT_TRAILER_CENTS": 350_000,
    "OZARK_NEW_UNIT_CONTRACT_PRICE_QUOTED": 11_125_000,
    "OZARK_NEW_UNIT_CONTRACT_PRICE_CONTRACTED": 11_220_000,
    "OZARK_NEW_UNIT_TOTAL_FEE": 882_193,
    "OZARK_NEW_UNIT_BALANCE_DUE": 12_102_193,
    "FISHING_RESIDENT_7DAY_FEE": 3_200,
}