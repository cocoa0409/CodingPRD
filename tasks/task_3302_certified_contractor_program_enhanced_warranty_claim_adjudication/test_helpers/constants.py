"""Domain thresholds and schedule constants from the PRD."""

# Logical clock startup default (PRD section 2.5).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Training credit minimums per tier (PRD section 3.2).
TIER_MIN_CREDITS = {"BRONZE": 4, "SILVER": 8, "GOLD": 12}

# Labor coverage windows (years) and caps (cents) per tier (PRD section 3.6 step 6).
TIER_LABOR_YEARS = {"BRONZE": 2, "SILVER": 5, "GOLD": 10}
TIER_LABOR_CAP_CENTS = {"BRONZE": 200000, "SILVER": 500000, "GOLD": 1000000}

# Tier -> material proration schedule (PRD section 3.6 step 1).
TIER_SCHEDULE = {"BRONZE": "STANDARD", "SILVER": "ENHANCED", "GOLD": "ENHANCED_PLUS"}

# Determination shares (PRD section 3.6 step 4).
DETERMINATION_SHARE = {"MANUFACTURER_DEFECT": 1.0, "MIXED": 0.5, "INSTALLATION_ERROR": 0.0}

# Liability factor bands keyed on filing_workmanship_score (PRD section 3.6 step 7).
LIABILITY_FACTOR_HIGH = 1.00  # score >= 80
LIABILITY_FACTOR_MID = 1.10  # 61 <= score <= 79
LIABILITY_FACTOR_LOW = 1.25  # score <= 60

# Workmanship deltas per determination (PRD section 3.6 step 8).
WORKMANSHIP_DELTA = {"MANUFACTURER_DEFECT": 0, "MIXED": -4, "INSTALLATION_ERROR": -10}

# Standing thresholds (PRD sections 3.6/3.7).
DECERT_THRESHOLD = 60
COMPLAINT_SUSPEND_THRESHOLD = 5
COMPLAINT_REVOKE_LIFETIME = 8
WORKMANSHIP_SCORE_FLOOR = 0
WORKMANSHIP_SCORE_CEILING = 100

# Required component types for registration activation (PRD section 3.3).
REQUIRED_COMPONENT_TYPES = ("SHINGLE", "UNDERLAYMENT", "STARTER", "RIDGE_CAP")

# Inspector capacity per (inspector_id, service_date) (PRD section 3.5).
INSPECTOR_DAILY_CAPACITY = 3

# Pagination defaults (PRD section 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Well-formed but nonexistent UUID used for 404 tests.
NONEXISTENT_UUID = "11111111-2222-3333-4444-555555555555"
