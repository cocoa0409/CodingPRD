"""Domain thresholds and pinned constants for the Electric Van Fleet Ops API.

Every value below is stated verbatim in the PRD; each is annotated with the
section that pins it. Do not invent or re-tune these values.
"""

# --- Platform constants -------------------------------------------------------

# PRD section 2.4: "At startup the logical clock reads exactly
# 2026-09-01T00:00:00Z, and it MUST NOT fall back to wall-clock time"
LOGICAL_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# PRD section 3.5: "when the delivery depot's state_code is one of the
# franchise-blocked states TX, MI, or WV and the order's delivery_method is
# DIRECT_DELIVERY, approval is refused with ERR_FRANCHISE_EXEMPTION_REQUIRED"
FRANCHISE_BLOCKED_STATES = ["TX", "MI", "WV"]

# PRD section 3.2: "any set of mutually overlapping projects in PERMITTING or
# INSTALLATION, the candidate project included, must have a combined crew_count
# of at most 4"
MAX_DEPOT_CREW = 4

# PRD section 3.9: "a conflict exists unless the new window ends at or before
# 45 minutes before the existing window's start, or begins at or after
# 45 minutes after the existing window's end"
VAN_TRAVEL_BUFFER_MINUTES = 45

# PRD section 3.4: "the moment failure_count reaches 2 the module
# auto-transitions from FAILED to SCRAPPED inside the same request"
MODULE_MAX_FAILURES = 2

# --- Supplier readiness scoring (PRD section 3.3) -----------------------------
# "Tier A requires on-time delivery of at least 95.0 percent, first-pass yield
#  of at least 98.0 percent, and exactly zero open corrective actions."
TIER_A_ON_TIME_PCT = 95.0
TIER_A_YIELD_PCT = 98.0
# "Tier B requires on-time of at least 85.0 percent, yield of at least
#  92.0 percent, and no more than 2 open corrective actions."
TIER_B_ON_TIME_PCT = 85.0
TIER_B_YIELD_PCT = 92.0
TIER_B_MAX_CORRECTIVE = 2

# --- Weekly production ramp gate (PRD section 3.5) ----------------------------
# "the weekly capacity is 8 base units plus, summed over every supplier,
#  24 units for each supplier at tier A, 10 for each at B, and 0 for C or
#  UNAUDITED"
RAMP_BASE_WEEKLY_UNITS = 8
TIER_WEEKLY_UNITS = {"A": 24, "B": 10, "C": 0, "UNAUDITED": 0}

# --- Depot charging demand gate (PRD section 3.6) -----------------------------
# "sum commissioned_capacity_kw over the depot's COMMISSIONED charging
#  projects ... multiply by a utilization factor of 0.8, and require the
#  result to be at least the draw of the in-service fleet plus the
#  commissioning candidate ... times 19.2 kW per vehicle"
PER_VEHICLE_DRAW_KW = 19.2
UTILIZATION_FACTOR = 0.8

# --- Battery end-of-life valuation (PRD section 3.9) --------------------------
# "When a report's measured_soh_pct falls strictly below 70.0, the vehicle's
#  battery_eol_status moves from NONE to EOL_REVIEW"
SOH_EOL_THRESHOLD = 70.0
# "multiplies a pack base value of 1800000 cents by a band multiplier keyed on
#  the reported state of health: 0.85 at 90 or above, 0.70 from 80 up to but
#  not including 90, 0.55 from 70 up to but not including 80, and 0.35 below
#  70, rounded half-up to integer cents"
PACK_BASE_VALUE_CENTS = 1800000
EOL_BAND_MULTIPLIERS = ((90.0, 0.85), (80.0, 0.70), (70.0, 0.55), (None, 0.35))
# "multiplies the allocated module's pack_kwh by 12000 cents per kWh and by
#  the exact reported state of health divided by 100"
RECOVERY_RATE_PER_KWH_CENTS = 12000

# --- Warranty settlement (PRD section 3.11) -----------------------------------
# "the covered labor cost is the line's labor_hours multiplied by 17500 cents
#  per hour and by the same class fraction"
LABOR_RATE_CENTS_PER_HOUR = 17500
# "minus a single per-claim deductible of 25000 cents, floored at zero"
DEDUCTIBLE_CENTS = 25000
# "1.0 for BATTERY, 1.0 for POWERTRAIN, 0.9 for CHARGING, 0.8 for BODY"
COVERAGE_PCT = {"BATTERY": 1.0, "POWERTRAIN": 1.0, "CHARGING": 0.9, "BODY": 0.8}

# --- Uptime credit (PRD section 3.10) -----------------------------------------
# "The first 2.0 percentage points of shortfall earn 2 percent of the monthly
#  fee per point, the next 3.0 points (beyond 2.0, up to 5.0) earn 5 percent
#  per point, and any shortfall beyond 5.0 points earns 10 percent per point;
#  the summed credit percentage is capped at 30.0 percent."
CREDIT_CAP_PCT = 30.0
CREDIT_TIER_1_WIDTH_PCT = 2.0
CREDIT_TIER_1_RATE = 2.0
CREDIT_TIER_2_WIDTH_PCT = 3.0
CREDIT_TIER_2_RATE = 5.0
CREDIT_TIER_3_RATE = 10.0

# --- Campaign rollout gate (PRD section 3.7) ----------------------------------
# "Leaving CANARY requires a cohort of at least 3 vehicles; leaving EXPANDED
#  requires at least 10"
CANARY_MIN_COHORT = 3
EXPANDED_MIN_COHORT = 10
# "The success rate ... must be at least 0.95 or the advance is refused"
ROLLOUT_SUCCESS_RATE_MIN = 0.95

# --- Delivery promise calculation (PRD section 3.5) ---------------------------
# "promised_delivery_date is computed from the logical clock as the confirm
#  date plus 28 base days, plus 7 additional days for each started block of
#  ten vans"
PROMISE_BASE_DAYS = 28
PROMISE_PER_TEN_VANS_DAYS = 7
# PRD section 3.3: "its promised_delivery_date pushed out by 14 days"
SUPPLY_RISK_PUSH_DAYS = 14

# --- Vehicle system defaults (PRD section 3.6) --------------------------------
# "Its software_version begins at the 1.0.0 factory baseline, software_hold is
#  false, current_soh_pct starts at 100.0, battery_eol_status is NONE"
SOFTWARE_VERSION_BASELINE = "1.0.0"
INITIAL_SOH_PCT = 100.0

# --- Pagination (PRD section 2.3) ---------------------------------------------
# "limit defaults to 10, with a minimum of 1 and a maximum of 100; offset
#  defaults to 0"
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0
