"""Domain constants — every value is a literal stated in PRD.md.

Sources (verified by grep against PRD.md):
  - Logical clock boot value: PRD section 2.4
  - Warranty coverage years / goodwill extension / parts support / reopen window: 3.2, 3.7
  - Settlement schedule and goodwill cap: 3.7
  - Clearance markdown tiers, coverage bands, cap: 3.5
  - Assembly fee components and travel: 3.6
  - Channel subsidy map: 3.4
  - Travel buffer, concurrency default: 3.6
  - Assembler quality and lifecycle thresholds: 3.6
  - Allocation waterfall constants: 3.4
  - Low-stock threshold: 3.8
  - Build sizing growth and season length: 3.3
  - Basis-point denominator, APP-PAIR token, default firmware: 2.6, 3.9, 3.2
"""

# --- Logical clock (PRD 2.4) ---
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Warranty coverage (years from the sale's sold_at, per component; PRD 3.2/3.7) ---
BURNER_COVERAGE_YEARS = 10
GRATE_COVERAGE_YEARS = 5
ELECTRONICS_COVERAGE_YEARS = 3
OTHER_COVERAGE_YEARS = 2
COMPONENT_COVERAGE_YEARS = {
    "BURNER": BURNER_COVERAGE_YEARS,
    "GRATE": GRATE_COVERAGE_YEARS,
    "ELECTRONICS": ELECTRONICS_COVERAGE_YEARS,
    "OTHER": OTHER_COVERAGE_YEARS,
}
GOODWILL_EXTENSION_DAYS = 90
MODEL_PARTS_SUPPORT_YEARS = 7
REOPEN_WINDOW_DAYS = 30

# --- Warranty settlement schedule (integer cents; PRD 3.7) ---
PART_COST_BURNER_CENTS = 3200
PART_COST_GRATE_CENTS = 2400
PART_COST_ELECTRONICS_CENTS = 4800
PART_COST_OTHER_CENTS = 1500
PART_COST_CENTS = {
    "BURNER": PART_COST_BURNER_CENTS,
    "GRATE": PART_COST_GRATE_CENTS,
    "ELECTRONICS": PART_COST_ELECTRONICS_CENTS,
    "OTHER": PART_COST_OTHER_CENTS,
}
LABOR_ALLOWANCE_BURNER_CENTS = 4500
LABOR_ALLOWANCE_GRATE_CENTS = 4500
LABOR_ALLOWANCE_ELECTRONICS_CENTS = 7500
LABOR_ALLOWANCE_OTHER_CENTS = 2500
LABOR_ALLOWANCE_CENTS = {
    "BURNER": LABOR_ALLOWANCE_BURNER_CENTS,
    "GRATE": LABOR_ALLOWANCE_GRATE_CENTS,
    "ELECTRONICS": LABOR_ALLOWANCE_ELECTRONICS_CENTS,
    "OTHER": LABOR_ALLOWANCE_OTHER_CENTS,
}
GOODWILL_CAP_CENTS = 10000

# --- Clearance markdown engine (PRD 3.5) ---
TIER1_MARKDOWN_PCT = 15
TIER2_MARKDOWN_PCT = 30
TIER3_MARKDOWN_PCT = 50
TIER2_START_WEEK = 3
TIER3_START_WEEK = 5
COVERAGE_HIGH_BP = 6000
COVERAGE_LOW_BP = 2000
OVERSTOCK_EXTRA_PCT = 10
UNDERSTOCK_RELIEF_PCT = 5
MAX_MARKDOWN_PCT = 70

# --- Assembly fee engine (integer cents; PRD 3.6) ---
BASE_ASSEMBLY_FEE_CENTS = 7999
IN_HOME_SURCHARGE_CENTS = 5005
INCLUDED_MILES = 15
RATE_PER_MILE_CENTS = 149
SUBSIDY_BP_HOME_CENTER = 2000
SUBSIDY_BP_SPECIALTY_DEALER = 1000
SUBSIDY_BP_DIRECT = 0
SUBSIDY_BP_BY_CHANNEL_TYPE = {
    "HOME_CENTER": SUBSIDY_BP_HOME_CENTER,
    "SPECIALTY_DEALER": SUBSIDY_BP_SPECIALTY_DEALER,
    "DIRECT": SUBSIDY_BP_DIRECT,
}

# --- Assembly scheduling (PRD 3.6) ---
TRAVEL_BUFFER_MINUTES = 45
DEFAULT_MAX_CONCURRENT_JOBS = 4

# --- Assembler quality / lifecycle (PRD 3.6) ---
NO_SHOW_SUSPEND_THRESHOLD = 3
NO_SHOW_PENALTY_BP = 1200
COMPLETION_BONUS_BP = 25
PROVISIONAL_WINDOW_DAYS = 90
REINSTATE_MIN_PROVISIONAL_BP = 7000
DECERTIFY_MAX_OFFICIAL_BP = 4000
QUALITY_BASE_BP = 10000

# --- Allocation waterfall (PRD 3.4) ---
MIN_CONSUMPTION_RATE_BP = 5000
MAX_REDISTRIB_SHARE_BP = 4000

# --- Parts availability (PRD 3.8) ---
LOW_STOCK_THRESHOLD = 10

# --- Build sizing (PRD 3.3) ---
GROWTH_BP = 11000
SEASON_WEEKS = 26

# --- General conventions (PRD 2.6, 3.9, 3.2) ---
BP_DENOMINATOR = 10000
APP_PAIR_TOKEN = "APP-PAIR"
DEFAULT_FIRMWARE_VERSION = "1.0.0"

__all__ = [name for name in dir() if name.isupper()]
