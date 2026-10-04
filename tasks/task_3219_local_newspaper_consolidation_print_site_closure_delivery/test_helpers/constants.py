"""Domain thresholds and pinned reference values for the news-operations API.

Every numeric value here is stated in the PRD's calculation and gate rules;
tests assert against these rather than re-deriving them inline.
"""

# ─── Print route transport economics ─────────────────────────────────
SPEED_MPH = 55
MILEAGE_BAND_1_MILES = 50
MILEAGE_BAND_1_RATE = 0.90
MILEAGE_BAND_2_MILES = 100
MILEAGE_BAND_2_RATE = 0.75
MILEAGE_BAND_3_RATE = 0.60
PER_STOP_TRANSPORT_FEE = 1.25

# ─── Print site closure savings ──────────────────────────────────────
SAVINGS_WINDOW_DAYS = 30
FIXED_PRESS_AVOIDED_CENTS = 180000

# ─── Delivery route nightly costing ──────────────────────────────────
TIER_1_MAX_COPIES = 7500
TIER_2_MAX_COPIES = 15000
TIER_3_MAX_COPIES = 30000
TIER_1_PCT = 0.00
TIER_2_PCT = 0.05
TIER_3_PCT = 0.10
TIER_4_PCT = 0.15
TERMINATED_STATUS_FACTOR = 0.85
ACTIVE_STATUS_FACTOR = 1.00

# ─── Press run time ──────────────────────────────────────────────────
MAKE_READY_MINUTES = 60
QUARTER_HOUR_MINUTES = 15
SPEED_FACTOR_TIER_1_MAX_PAGES = 8
SPEED_FACTOR_TIER_2_MAX_PAGES = 16

# ─── Single-copy assortment decision ─────────────────────────────────
NEWSSTAND_SELL_THROUGH_PCT = 0.65

# ─── Subscriber economics ────────────────────────────────────────────
CARRIER_LABOR_CENTS = 85
PER_ISSUE_HANDLING_CENTS = 40
PRINT_COST_PER_ISSUE_CENTS = CARRIER_LABOR_CENTS + PER_ISSUE_HANDLING_CENTS  # 125
ACTIVE_CONTRACT_CAP_CENTS = 5000
RETENTION_OFFER_VALUE_THRESHOLD_CENTS = 20000
LOW_VALUE_CREDIT_THRESHOLD_CENTS = 5000
LONG_TERM_DAYS = 180

# ─── Newsroom severance ──────────────────────────────────────────────
SEVERANCE_MONTHS = 2.15
SALARY_LOAD_MULTIPLIER = 1.65
MITIGATION = 0.25

# ─── Late edition penalty ────────────────────────────────────────────
PER_MINUTE_PENALTY_CENTS = 45
SPORTS_EDITION_MULTIPLIER = 2
CORRECTION_MULTIPLIER = 3

# ─── Correction re-run ───────────────────────────────────────────────
REPRINT_HOURLY_CENTS = 2500.00
RERUN_COST_MULTIPLIER = 1.40

# ─── Legal-notice ratio gate ─────────────────────────────────────────
MIN_ON_TIME_RATIO_PCT_DEFAULT = 90

# ─── Frequency reduction ─────────────────────────────────────────────
NOTICE_PERIOD_DAYS = 14

# ─── Endpoint prefixes ───────────────────────────────────────────────
API_PREFIX = "/regional-news-ops"
CLOCK_PATH = "/_clock/set_current_utc"
PRINT_VOLUME_PATH = f"{API_PREFIX}/_print-volume/records"

# ─── Pinned reference scenario ───────────────────────────────────────
HUB_NAME = "North Ridge Media Group"
HUB_TOTAL_HEADCOUNT = 30
HUB_TONNAGE_BUDGET_CENTS = 5_000_000
HUB_TRANSFER_CEILING_CENTS = 20_000

SITE_KOT = {
    "code": "KOT",
    "press_units": 2,
    "shifts_per_night": 2,
    "copies_per_hour_per_press": 25000,
    "max_concurrent_departures": 2,
    "allocation_method": "PRIORITY",
    "distinct_shifts_per_night": 4,
    "loading_slot_minutes": 30,
}
SITE_KOT_CAPACITY = 2 * 2 * 8 * 25000  # 800000

SITE_CED = {
    "code": "CED",
    "press_units": 1,
    "shifts_per_night": 2,
    "copies_per_hour_per_press": 25000,
    "max_concurrent_departures": 2,
    "allocation_method": "PROPORTIONAL",
    "distinct_shifts_per_night": 2,
    "loading_slot_minutes": 30,
}
# 1 * 2 * 8 * 25000 = 400000 installed capacity; the round-trip test creates CED
# with a non-default loading slot, so that entry is kept separate.
SITE_CED_CAPACITY = 1 * 2 * 8 * 25000  # 400000
SITE_CED_NON_DEFAULT_SLOT = dict(SITE_CED, loading_slot_minutes=45)

REGION_NORTH = {"name": "North", "daily_headcount_floor": 4, "daily_headcount_cap": 10, "allocation_priority": 1}
REGION_SOUTH = {"name": "South", "daily_headcount_floor": 3, "daily_headcount_cap": 8, "allocation_priority": 2}

MARKET_RIVERTON = {
    "name": "Riverton",
    "per_copy_revenue_cents": 45,
    "daily_route_cost_ceiling_cents": 9000,
    "weighted_demand_units": 7000,
    "print_edition_per_week": 7,
    "publication_deadline_utc": "05:30",
    "on_time_margin_minutes": 30,
    "guaranteed_floor_copies": 8000,
    "single_copy_market_rule": "carrier",
}
MARKET_FALLOW = {
    "name": "Fallow",
    "per_copy_revenue_cents": 45,
    "daily_route_cost_ceiling_cents": 9000,
    "weighted_demand_units": 6000,
    "print_edition_per_week": 7,
    "publication_deadline_utc": "05:30",
    "on_time_margin_minutes": 30,
    "guaranteed_floor_copies": 0,
    "single_copy_market_rule": "carrier",
}

ROUTE_KOT_RIVERTON = {
    "transit_minutes": 120,
    "dispatch_cutoff_utc": "01:00",
    "is_direct_hop": True,
    "buffer_minutes": 45,
}
# distance_miles = round(120/60*55, 2) = 110.00
# marginal_mileage_cost = 50*0.90 + 60*0.75 = 90.00
ROUTE_KOT_DISTANCE_MILES = 110.00
ROUTE_KOT_MILEAGE_COST = 90.00
# route_transport_cost with 5 stops = 90.00 + 6.25 = 96.25; with 3 stops = 93.75
ROUTE_TRANSPORT_5_STOPS = 96.25
ROUTE_TRANSPORT_3_STOPS = 93.75

CONTRACTOR_CEDAR = {
    "name": "Cedar Hill Carriers",
    "pay_basis": "PER_STOP",
    "per_copy_rate_cents": 45,
    "min_stop_guarantee": 3,
    "net_60_available": True,
    "cost_per_copy_ceiling_cents": 600,
    "last_load_claim_weight_lbs": 0,
    "sanction_reason_code": "NONE",
}

DELIVERY_ROUTE_R1 = {
    "route_code": "R1",
    "stop_capacity": 6,
    "per_stop_fee_cents": 1150,
    "dist_per_stop_miles": 3.0,
    "cost_per_copy_ceiling_cents": 600,
    "printed_copies_surcharge_cents": 0,
    "cost_run_date": "2026-09-10",
}

STOP_S1 = {
    "stop_code": "S1",
    "contracted_daily_copies": 500,
    "contracted_daily_fee_cents": 1200,
    "pause_start_date": "2026-10-05",
    "pause_end_date": "2026-10-09",
}

CLOCK_2026_09_01 = "2026-09-01T00:00:00Z"
CLOCK_2026_09_30 = "2026-09-30T00:00:00Z"

THRESHOLDS = {
    "SPEED_MPH": SPEED_MPH,
    "MILEAGE_BAND_1_MILES": MILEAGE_BAND_1_MILES,
    "MILEAGE_BAND_2_MILES": MILEAGE_BAND_2_MILES,
    "PER_STOP_TRANSPORT_FEE": PER_STOP_TRANSPORT_FEE,
    "SAVINGS_WINDOW_DAYS": SAVINGS_WINDOW_DAYS,
    "FIXED_PRESS_AVOIDED_CENTS": FIXED_PRESS_AVOIDED_CENTS,
    "TIER_1_MAX_COPIES": TIER_1_MAX_COPIES,
    "TIER_2_MAX_COPIES": TIER_2_MAX_COPIES,
    "TIER_3_MAX_COPIES": TIER_3_MAX_COPIES,
    "TERMINATED_STATUS_FACTOR": TERMINATED_STATUS_FACTOR,
    "MAKE_READY_MINUTES": MAKE_READY_MINUTES,
    "NEWSSTAND_SELL_THROUGH_PCT": NEWSSTAND_SELL_THROUGH_PCT,
    "CARRIER_LABOR_CENTS": CARRIER_LABOR_CENTS,
    "PER_ISSUE_HANDLING_CENTS": PER_ISSUE_HANDLING_CENTS,
    "ACTIVE_CONTRACT_CAP_CENTS": ACTIVE_CONTRACT_CAP_CENTS,
    "LOW_VALUE_CREDIT_THRESHOLD_CENTS": LOW_VALUE_CREDIT_THRESHOLD_CENTS,
    "LONG_TERM_DAYS": LONG_TERM_DAYS,
    "SEVERANCE_MONTHS": SEVERANCE_MONTHS,
    "SALARY_LOAD_MULTIPLIER": SALARY_LOAD_MULTIPLIER,
    "MITIGATION": MITIGATION,
    "PER_MINUTE_PENALTY_CENTS": PER_MINUTE_PENALTY_CENTS,
    "REPRINT_HOURLY_CENTS": REPRINT_HOURLY_CENTS,
    "RERUN_COST_MULTIPLIER": RERUN_COST_MULTIPLIER,
    "MIN_ON_TIME_RATIO_PCT_DEFAULT": MIN_ON_TIME_RATIO_PCT_DEFAULT,
    "NOTICE_PERIOD_DAYS": NOTICE_PERIOD_DAYS,
}

TEST_DEFAULTS = {
    "HUB": {
        "name": HUB_NAME,
        "total_newsroom_headcount": HUB_TOTAL_HEADCOUNT,
        "max_print_tonnage_budget_cents": HUB_TONNAGE_BUDGET_CENTS,
        "transfer_cost_ceiling_cents": HUB_TRANSFER_CEILING_CENTS,
    },
    "SITE": SITE_KOT,
    "REGION": REGION_NORTH,
    "MARKET": MARKET_RIVERTON,
    "ROUTE": ROUTE_KOT_RIVERTON,
    "CONTRACTOR": CONTRACTOR_CEDAR,
    "DELIVERY_ROUTE": DELIVERY_ROUTE_R1,
    "STOP": STOP_S1,
}