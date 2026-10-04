"""Domain thresholds and numeric constants.

Every value below is stated verbatim in PRD.md (§2.5, §3.1-§3.9); each entry
carries the PRD section and the literal phrasing it comes from. Do NOT add a
constant here unless its value appears in PRD prose.
"""

# --- Logical clock (PRD §2.5) ----------------------------------------------
# "the logical clock's startup default is exactly 2026-09-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# --- Validity windows --------------------------------------------------------
# PRD §3.1: "expiration_date is fixed at the issuance instant plus 1825 days"
JD_VALIDITY_DAYS = 1825
# PRD §3.7: "fixes `expiration_date` at the issue instant plus 1825 days"
PERMIT_VALIDITY_DAYS = 1825

# --- Appeal window (PRD §3.2) ------------------------------------------------
# "the gap between the filing clock and the determination's `issued_date` is at
#  most 60 days — exactly 60 days is allowed, one day more is rejected"
APPEAL_WINDOW_DAYS = 60

# --- Public notice comment window (PRD §3.5) ---------------------------------
# "fixes `comment_period_days` to the payload value if supplied, defaulting to
#  30 days; any supplied value must lie between 15 and 60 days inclusive"
COMMENT_PERIOD_DEFAULT_DAYS = 30
COMMENT_PERIOD_MIN_DAYS = 15
COMMENT_PERIOD_MAX_DAYS = 60

# --- General-permit eligibility (PRD §3.3) ------------------------------------
# "the `total_impact_acres` must not exceed 0.50 acres (exactly 0.50 remains
#  eligible), and every impact line's resource type must be `EMERGENT_MARSH`
#  or `STREAM`"
GP_MAX_TOTAL_IMPACT_ACRES = 0.50
GP_ALLOWED_RESOURCE_TYPES = ["EMERGENT_MARSH", "STREAM"]
GP_PERMIT_CODES = ["NWP-29", "NWP-39"]

# --- Compensatory mitigation trigger (PRD §3.3) -------------------------------
# "derives `compensatory_mitigation_required` as true exactly when
#  `total_impact_acres` is strictly greater than 0.10 acres"
MITIGATION_TRIGGER_ACRES = 0.10

# --- Mitigation credit requirement (PRD §3.6) ---------------------------------
# "the base ratio is 2.0 credits per acre for `EMERGENT_MARSH`, 3.0 for
#  `FORESTED_WETLAND`, 1.5 for `OPEN_WATER`, and 1.0 for `STREAM`"
RATIO_BY_RESOURCE_TYPE = {
    "EMERGENT_MARSH": 2.0,
    "FORESTED_WETLAND": 3.0,
    "OPEN_WATER": 1.5,
    "STREAM": 1.0,
}
# "finally by the after-the-fact multiplier, 1.5 when `is_after_the_fact` is
#  true and 1.0 otherwise"
ATF_MULTIPLIER = 1.5
ATF_MULTIPLIER_NONE = 1.0
# "The location multiplier is 1.0 when every `PURCHASED` credit transaction of
#  the plan draws on a bank whose `service_area_watersheds` contains the site's
#  `watershed_code`, and 1.25 otherwise"
LOCATION_MULT_IN_BASIN = 1.0
LOCATION_MULT_OUT_OF_BASIN = 1.25
# "apply 1.0 when that lag is at most 365 days, 1.10 when it is between 366 and
#  730 days inclusive, and 1.20 once it exceeds 730 days"
LAG_TIER1_MAX_DAYS = 365
LAG_TIER2_MAX_DAYS = 730
LAG_MULT_TIER1 = 1.0
LAG_MULT_TIER2 = 1.10
LAG_MULT_TIER3 = 1.20

# --- In-lieu fee rates (PRD §3.6) ---------------------------------------------
# "40000 dollars for `EMERGENT_MARSH`, 55000 for `FORESTED_WETLAND`, 30000 for
#  `OPEN_WATER`, and 25000 for `STREAM`"
ILF_RATE_PER_CREDIT = {
    "EMERGENT_MARSH": 40000.0,
    "FORESTED_WETLAND": 55000.0,
    "OPEN_WATER": 30000.0,
    "STREAM": 25000.0,
}

# NOTE: the PRD (§3.6) says `assurance_required_dollars` "is computed and
# stored" for PERMITTEE_RESPONSIBLE and COMBINATION plans but never publishes
# the formula or a per-credit rate. No assurance-rate constant is defined
# here; tests must read the server-computed `assurance_required_dollars` from
# the plan response instead of hardcoding a value.

# --- Public interest review (PRD §3.5) ----------------------------------------
# "the `pir_score` is the weighted sum — 0.40 times the environmental
#  component, 0.35 times the economic component, and 0.25 times the
#  navigation component"
PIR_WEIGHT_ENVIRONMENTAL = 0.40
PIR_WEIGHT_ECONOMIC = 0.35
PIR_WEIGHT_NAVIGATION = 0.25
# "negative 10.0 points per impacted acre ... on the standard variant, or —
#  for an after-the-fact application — negative 15.0 points per impacted acre
#  plus a flat negative 10.0 deterrence adjustment"
PIR_ENV_HARM_PER_ACRE_STANDARD = -10.0
PIR_ENV_HARM_PER_ACRE_ATF = -15.0
PIR_ENV_ATF_DETERRENCE = -10.0
# "adds 5.0 points for every entry in `minimization_steps`"
PIR_POINTS_PER_MINIMIZATION_STEP = 5.0
# "adds a `secured_bonus` of 20.0 points when the application's mitigation plan
#  stands in `CREDITS_SECURED`, `ACTIVE`, or `COMPLETED` (zero otherwise)"
PIR_SECURED_BONUS = 20.0
# "subtracts 15.0 points for every agency comment of this application that is
#  `ADVISORY` and still `FILED`, and adds 5.0 points for every `CONCURRENCE`
#  comment of this application regardless of that comment's status"
PIR_UNRESOLVED_ADVISORY_PENALTY = -15.0
PIR_CONCURRENCE_BONUS = 5.0
# "take `estimated_cost_dollars`, subtract 250000.0 dollars, divide by
#  10000.0 dollars, and clamp the result so it never falls below negative
#  100.0 or above positive 100.0"
PIR_ECONOMIC_NEUTRAL_DOLLARS = 250000.0
PIR_ECONOMIC_SCALE_DOLLARS = 10000.0
PIR_ECONOMIC_CLAMP = 100.0
# "The navigation component is negative 10.0 points when any impact line
#  touches `OPEN_WATER` or `STREAM`, and positive 15.0 points when none does."
PIR_NAVIGATION_WITH_WATER_IMPACT = -10.0
PIR_NAVIGATION_WITHOUT_WATER_IMPACT = 15.0
PIR_NAVIGATION_RESOURCE_TYPES = ["OPEN_WATER", "STREAM"]
# "The `pir_outcome` is `FAVORABLE` when the score is at least 0.0"
PIR_FAVORABLE_MIN_SCORE = 0.0

# --- Bank credit pricing tiers (PRD §3.6) -------------------------------------
# "apply a multiplier of 1.0 when that sold fraction is less than 0.5, 1.15
#  when it is at least 0.5 but less than 0.8, and 1.30 when it is at least 0.8"
PRICE_TIER1_MAX_FRACTION = 0.5
PRICE_TIER2_MAX_FRACTION = 0.8
PRICE_TIER1_MULT = 1.0
PRICE_TIER2_MULT = 1.15
PRICE_TIER3_MULT = 1.30

# --- Enforcement penalty accrual (PRD §3.9) -----------------------------------
# "`penalty_accrued_dollars` accrues at 250.0 dollars per unauthorized acre
#  per day ... capped at 500000.0 dollars"
PENALTY_RATE_PER_ACRE_DAY = 250.0
PENALTY_CAP_DOLLARS = 500000.0
# "the case closes and `penalty_final_dollars` is fixed at half of the accrued
#  penalty, rounded half-up to two decimal places"
RESTORATION_GOOD_FAITH_OFFSET = 0.5
# "the system sets `restoration_deadline` to the current clock plus 90 days"
RESTORATION_DEADLINE_DAYS = 90
# "returning the case to `RESOLUTION_PENDING` with `restoration_deadline`
#  reset to the current clock plus 60 days"
EXTENSION_DAYS = 60

# --- Monitoring schedule (PRD §3.7, §3.8) -------------------------------------
# "exactly five monitoring reports are generated for the new permit and plan —
#  `period_index` running 1 through 5, each report's `due_date` set at the
#  permit's `issue_date` plus 365 days times its period index"
MONITORING_REPORT_COUNT = 5
MONITORING_INTERVAL_DAYS = 365
# PRD §3.8/§2.5: "a report that stays `OVERDUE` more than 60 days past its
#  `due_date` while its permit is `ACTIVE` is a compliance breach"
OVERDUE_BREACH_DAYS = 60

# --- Permit numbering (PRD §3.7) ----------------------------------------------
# "a `permit_number` formed as `WP-` followed by a four-digit zero-padded
#  sequential count of issued permits starting at 1 — the first permit is
#  `WP-0001`"
PERMIT_NUMBER_PREFIX = "WP-"
FIRST_PERMIT_NUMBER = "WP-0001"

# --- Pinned special conditions (PRD §3.7, quoted verbatim) --------------------
SPECIAL_CONDITIONS_GENERAL = [
    "SC-GP-01: Erosion and sediment controls must be maintained for the duration of the authorized work",
    "SC-GP-02: Work must be completed within the general permit activity limits",
]
SPECIAL_CONDITIONS_INDIVIDUAL = [
    "SC-IP-01: Five years of mitigation monitoring reports are required",
    "SC-IP-02: Long-term stewardship must be maintained by the designated stewardship entity",
    "SC-IP-03: Compensatory mitigation must remain secured for the life of the project",
]

# --- Reference scenario values shared by many fixtures -------------------------
# (Not PRD rules — conventional fixture inputs matching the design recipes.)
DEFAULT_STATE_CODE = "VA"
DEFAULT_WATERSHED_CODE = "18020101"
OUT_OF_STATE_CODE = "MD"
OUT_OF_BASIN_WATERSHED_CODE = "18020202"
DEFAULT_BANK_CAPACITY_FW = 20.0
DEFAULT_BANK_PRICE_FW = 30000.0
DEFAULT_IMPACT_RESOURCE_TYPE = "FORESTED_WETLAND"
DEFAULT_IMPACT_ACRES = 2.0
DEFAULT_ESTIMATED_COST = 750000.0
DEFAULT_BUY_CREDITS = 7.0  # >= 6.60 final requirement after one lag tier
