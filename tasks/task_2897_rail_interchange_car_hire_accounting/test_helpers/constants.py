"""Named constants drawn from the Rail Interchange & Car Hire Accounting PRD.

Every value here is stated verbatim in the PRD; nothing is inferred from an
implementation.  Money is always integer cents.
"""

# --- §2.4 Logical clock -----------------------------------------------------
SERVER_START_CLOCK_UTC = "2026-08-01T00:00:00Z"
CLOCK_ENDPOINT = "/_clock/set_current_utc"

# --- §2.3 Pagination --------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- §3.1 Railroad ---------------------------------------------------------
DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS = 100000000

# --- §3.3 Interchange capture ----------------------------------------------
LATE_REPORT_LIMIT_HOURS = 168

# --- §3.4 Hire pricing -----------------------------------------------------
MILLICENTS_PER_CENT = 1000

# --- §3.5 Reclaim claims ---------------------------------------------------
MIN_RECLAIM_HOURS = 24
RECLAIM_FILING_WINDOW_DAYS = 60
DETENTION_SPLIT_PCT = 0.5
FULL_SPLIT_PCT = 1.0
EMBARGO_COOLING_GAP_HOURS = 24

# --- §3.6 Empty-car return obligations -------------------------------------
REVERSE_ROUTE_PENALTY_PCT = 0.25

# --- §3.7 Repair billing ---------------------------------------------------
REPAIR_LABOR_RATE_CENTS_PER_HOUR = 9500
REPAIR_HANDLING_FEE_PCT = 0.075
REPAIR_PREAUTH_THRESHOLD_CENTS = 150000
MAX_COUNTER_BILL_ROUNDS = 2

# --- §3.8 Settlement -------------------------------------------------------
FEE_TIER_BREAK_CENTS = 500000
FEE_TIER1_PCT = 0.005
FEE_TIER2_PCT = 0.0035
DISPUTE_WINDOW_DAYS = 30
REOPEN_WINDOW_DAYS = 30
MAX_DISPUTE_ROUNDS = 3

# --- §3.9 Corrections / exposure -------------------------------------------
CORRECTION_CONFIRM_WINDOW_HOURS = 72
PROJECTION_HORIZON_HOURS = 72

# --- Enumerations (§3.1 - §3.9) --------------------------------------------
RAILROAD_STATUSES = ("ACTIVE", "SUSPENDED")
JUNCTION_STATUSES = ("OPEN", "CLOSED")
TIME_COMPONENT_MODES = ("PER_DIEM", "HOURLY")
CUSTODY_STATUSES = ("ON_HOME_ROAD", "ON_FOREIGN_ROAD")
MECHANICAL_STATUSES = ("SERVICEABLE", "BAD_ORDER", "UNDER_REPAIR")
ROUTING_STATUSES = (
    "NO_OBLIGATION",
    "OBLIGATION_ACTIVE",
    "OBLIGATION_MET",
    "OBLIGATION_VIOLATED",
)
LOAD_STATUSES = ("LOADED", "EMPTY")
EVENT_TYPES = ("INTERCHANGE_DELIVERY", "INTERCHANGE_REJECTION")
EVENT_STATUSES = ("RECORDED", "SUPERSEDED", "VOID")
EVENT_SOURCES = ("CLERK_CAPTURE", "CORRECTION_APPLY")
MOVEMENT_STATUSES = ("OPEN", "CLOSED", "VOID")
RECLAIM_REASONS = ("BAD_ORDER", "EMBARGO", "CUSTOMER_DETENTION")
RECLAIM_STATUSES = ("FILED", "ALLOWED", "DISALLOWED", "WITHDRAWN")
EMBARGO_STATUSES = ("ACTIVE", "LIFTED")
DEFECT_CLASSES = ("HANDLING_DAMAGE", "NORMAL_WEAR", "OWNER_APPLIANCE_DEFECT")
RESPONSIBILITY_RULES = ("HANDLING_LINE_RULE", "OWNER_RESPONSIBILITY_RULE")
REPAIR_BILL_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SETTLED")
CYCLE_STATUSES = ("OPEN", "COMPUTED", "EXCHANGED", "SETTLED", "REOPENED", "ARCHIVED")
CYCLE_VARIANTS = ("AS_REPORTED", "RECONCILED")
EXPOSURE_VARIANTS = ("SNAPSHOT", "PROJECTED")
DISPUTE_REASONS = (
    "HIRE_RATE_MISAPPLIED",
    "MILEAGE_DISCREPANCY",
    "RECLAIM_DENIED_IMPROPERLY",
    "REPAIR_RESPONSIBILITY",
    "DUPLICATE_CHARGE",
)
DISPUTE_STATUSES = ("OPEN", "COUNTERED", "ACCEPTED", "WITHDRAWN")
CORRECTION_TYPES = ("MISSED_EVENT_INSERT", "TIMESTAMP_AMEND", "ERRONEOUS_EVENT_VOID")
CORRECTION_DIRECTIONS = ("FILER_DELIVERS", "FILER_RECEIVES")
CORRECTION_STATUSES = ("FILED", "CONFIRMED", "APPLIED", "REJECTED", "EXPIRED")
LEDGER_ENTRY_TYPES = (
    "HIRE_CHARGE",
    "REPAIR_CHARGE",
    "RECLAIM_CREDIT",
    "RECLAIM_REVERSAL",
    "CORRECTION_ADJUSTMENT",
    "DISPUTE_ADJUSTMENT",
    "RECOMPUTE_REVERSAL",
    "SETTLEMENT_PAYMENT",
)
SUPPORTING_EVENT_VOIDED = "SUPPORTING_EVENT_VOIDED"

# --- Reference car types used across the suite (§3.1 rate book) ------------
XM_CAR_TYPE = {
    "car_type_code": "XM",
    "description": "Box car, cushioned underframe",
    "time_component_mode": "PER_DIEM",
    "free_time_hours": 4,
    "per_diem_rate_cents": 2350,
    "tier2_threshold_days": 2,
    "tier2_per_diem_rate_cents": 3100,
    "mileage_rate_millicents_per_mile": 2350,
    "loaded_mileage_only": True,
}
HR_CAR_TYPE = {
    "car_type_code": "HR",
    "description": "Hourly-rated refrigerator car",
    "time_component_mode": "HOURLY",
    "free_time_hours": 4,
    "hourly_rate_cents": 150,
    "mileage_rate_millicents_per_mile": 2350,
    "loaded_mileage_only": False,
}
FB_CAR_TYPE = {
    "car_type_code": "FB",
    "description": "Flat car, bulkhead",
    "time_component_mode": "PER_DIEM",
    "free_time_hours": 0,
    "per_diem_rate_cents": 2000,
    "tier2_threshold_days": 5,
    "tier2_per_diem_rate_cents": 2600,
    "mileage_rate_millicents_per_mile": 1500,
    "loaded_mileage_only": True,
}

# A UUID that is syntactically valid but names no row anywhere.
UNUSED_UUID = "66666666-6666-4666-8666-666666666666"
