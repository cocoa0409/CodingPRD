"""Domain constants — every value below is stated verbatim in the PRD.

Numeric thresholds come from the calculation prose in PRD §3 and the global
rules in PRD §2. They are collected here so tests assert against the same
numbers the contract publishes.
"""

# --- Logical clock (PRD §2.5) ------------------------------------------------
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

# --- Lot grading thresholds (PRD §3.2) ---------------------------------------
REJECT_DEFECT_PCT = 8.0        # defect_pct >= 8.0 -> REJECT override
DEFECT_A_MAX = 3.0             # defect tier A when defect_pct < 3.0
DEFECT_B_MAX = 5.0             # defect tier B when defect_pct < 5.0, else C
GRAVITY_A_MIN = 1.080
GRAVITY_B_MIN = 1.070
GRAVITY_C_MIN = 1.060          # below 1.060 -> REJECT
SUGAR_A_MAX = 2.0
SUGAR_B_MAX = 3.0
SUGAR_C_MAX = 4.0              # above 4.0 -> REJECT

# --- Grade price multipliers (PRD §3.1 / §3.2) -------------------------------
GRADE_A_MULT = 1.08
GRADE_B_MULT = 1.03
GRADE_C_MULT = 0.88
GRADE_REJECT_MULT = 0.0

# --- Storage decay at settlement (PRD §3.1) -----------------------------------
DAILY_LOSS_PCT = 0.02
POSTURE_FACTOR_NORMAL = 1.0
POSTURE_FACTOR_WATCH = 1.5
POSTURE_FACTOR_QUARANTINED = 3.0
MAX_LOSS_PCT = 15.0
DOWNGRADE_LOSS_PCT = 10.0      # downgrade only when storage_loss_pct > 10.0
SECONDS_PER_DAY = 86400

# --- Facility posture thresholds (PRD §3.3), inclusive -----------------------
QUARANTINE_DISEASE_PCT = 6.0
QUARANTINE_SPROUT = 4.0
WATCH_DISEASE_PCT = 3.0
WATCH_SPROUT = 2.0

# --- Byproduct tariff, cents per cwt (PRD §3.3) -------------------------------
TARIFF_CATTLE_FEED = 900
TARIFF_STARCH_RECOVERY = 1400
TARIFF_CONDEMNED_WASTE = 0

# --- Production yields, cases per cwt (PRD §3.6) ------------------------------
YIELD_STRAIGHT = 0.62
YIELD_CRINKLE = 0.58
YIELD_WEDGE = 0.66
YIELD_SHOESTRING = 0.55
REWORK_RETENTION = 0.96        # re-entry keeps 96% of previous actual_cases
CHANGEOVER_MINUTES = 60        # cross-family changeover buffer
COLOR_TOLERANCE_UNITS = 0.5    # qa-release |measured - target| <= 0.5

# --- Sensory panel gate (PRD §3.4) --------------------------------------------
PANEL_SCORE_MIN = 7.0

# --- Plant weekly case pool (PRD §2.7) ----------------------------------------
PLANT_WEEK_CAPACITY_CASES = 100000

# --- Cold chain / settlement of shipments (PRD §3.7) --------------------------
EXCURSION_LIMIT_MINUTES = 30   # flag when minutes_above_setpoint > 30
EXCURSION_DISCOUNT_MULT = 0.90
SALVAGE_CREDIT_MULT = 0.85
FILL_RATE_FLOOR_PCT = 85.0

# --- Contract auto-fulfillment (PRD §3.1) --------------------------------------
AUTO_FULFILL_RATIO = 0.98

# --- A syntactically valid but never-allocated UUID (used by 404 recipes) -----
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# --- Role spellings (PRD §2.1) -------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_GROWER_RELATIONS_MANAGER = "GrowerRelationsManager"
ROLE_GROWER = "Grower"
ROLE_STORAGE_OPERATOR = "StorageOperator"
ROLE_QA_LEAD = "QualityAssuranceLead"
ROLE_PRODUCTION_PLANNER = "ProductionPlanner"
ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_CHAIN_CUSTOMER = "ChainCustomer"
ROLE_LOGISTICS_COORDINATOR = "LogisticsCoordinator"
