"""Domain thresholds — numeric constants from PRD §3 narratives."""

# Logical clock (PRD §2.4): server startup reads exactly this instant.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Award packaging (PRD §3.8).
PELL_MAX_CENTS = 739500            # federal Pell maximum ($7,395)
COA_FULL_TIME_CENTS = 800000       # cost of attendance, FULL_TIME ($8,000)
COA_HALF_TIME_CENTS = 500000       # cost of attendance, HALF_TIME ($5,000)
COA_LESS_THAN_HALF_TIME_CENTS = 200000  # cost of attendance, LESS_THAN_HALF_TIME ($2,000)
COA_BY_INTENSITY = {
    "FULL_TIME": COA_FULL_TIME_CENTS,
    "HALF_TIME": COA_HALF_TIME_CENTS,
    "LESS_THAN_HALF_TIME": COA_LESS_THAN_HALF_TIME_CENTS,
}

# R2T4 / refund rules (PRD §3.8).
R2T4_EARNED_CLIFF = 0.60           # strict > : exactly 0.60 still triggers a return
INST_HALF_REFUND_WINDOW_DAYS = 14  # half tuition through census + 14 days

# Counselor contact cadence (PRD §3.3).
MAX_CONTACTS_PER_7D = 3
CADENCE_WINDOW_HOURS = 168

# Adjunct planning (PRD §3.7).
ADJUNCT_SECTION_SIZE = 30

# Transfer credit cap (PRD §3.5): cap = floor(total * 3/4).
TRANSFER_CAP_NUM = 3
TRANSFER_CAP_DEN = 4

# Retention outreach cadence (PRD §3.9): strictly less than 14 days rejects.
MIN_DAYS_BETWEEN_OUTREACH = 14

# Standard test term used across scenarios (all dates >= clock start).
TERM_FIXTURE = {
    "name": "2026 Fall A",
    "start_date": "2026-10-05",
    "add_drop_end_date": "2026-10-12",
    "census_date": "2026-10-19",
    "end_date": "2026-12-13",
}
# Derived schedule anchors for TERM_FIXTURE (70 inclusive days; midpoint +35d).
TERM_CENSUS_DATE = TERM_FIXTURE["census_date"]      # entry 1 release date
TERM_MIDPOINT_DATE = "2026-11-09"                   # entry 2 release date
TERM_OPEN_CLOCK = "2026-09-05T00:00:00Z"            # exactly start_date - 30d
TERM_START_CLOCK = "2026-10-05T00:00:00Z"
TERM_CENSUS_CLOCK = "2026-10-19T00:00:00Z"

TEST_DEFAULTS = {
    "TOTAL_CREDITS": 120,
    "TUITION_CENTS": 500000,
    "CASELOAD_CAP": 5,
    "STATE_CODE": "CO",
    "AUTH_EFFECTIVE_FROM": "2026-01-01",
}
