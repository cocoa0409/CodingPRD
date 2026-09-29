"""Domain thresholds and canonical scenario literals from the PRD."""

# ─── Review-threshold determination (PRD §3.3) ────────
CAPITAL_COST_REVIEW_THRESHOLD_CENTS = 500_000_000
BED_DELTA_REVIEW_THRESHOLD = 10
LOOKBACK_MONTHS = 24
ALWAYS_REVIEWABLE_SERVICE_TYPES = (
    "OPEN_HEART_SURGERY",
    "MRI_UNIT",
    "NURSING_HOME_BEDS",
)

# ─── Need methodology (PRD §3.2, §2.6) ───────────────
DAYS_PER_YEAR = 365
PATIENT_DAY_DECIMALS = 4
PROVISIONAL_BED_DECIMALS = 4

# ─── Comparative score weights (PRD §3.7) ────────────
SCORE_WEIGHTS = {
    "need_conformity_score": 0.30,
    "financial_feasibility_score": 0.25,
    "cost_containment_score": 0.20,
    "access_underserved_score": 0.15,
    "quality_record_score": 0.10,
}
MIN_ACTIVE_SCORE_SHEETS_FOR_DECISION = 2
COMPARATIVE_SCORE_DECIMALS = 2

# ─── Certificate fiscal and temporal rules (PRD §3.8) ─
EXPENDITURE_CEILING_MULTIPLIER = 1.05
MAX_CUMULATIVE_EXTENSION_DAYS = 540
MAX_DAYS_PER_EXTENSION_GRANT = 365
DEFAULT_REQUIRED_COMPLETION_PCT_AT_MILESTONE = 25
SINGLE_PERIOD_EXPENDITURE_MULTIPLIER = 2

# ─── Appeal window (PRD §3.4) ────────────────────────
APPEAL_WINDOW_DAYS = 30

# ─── Compliance standing (PRD §3.1) ──────────────────
STRIKES_TO_RESTRICTED = 2
STRIKES_TO_BARRED = 4

# ─── Hearing rooms (PRD §3.1) ────────────────────────
DEFAULT_SETUP_BUFFER_MINUTES = 60

# ─── Pagination (PRD §2.3) ───────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ─── Logical clock (PRD §2.4) ────────────────────────
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Canonical scenario literals ─────────────────────
# The recurring planning area, formula, calendar and filings that the whole
# test suite builds its scenarios from.

NORTH_HSA = {
    "code": "HSA-NORTH",
    "name": "North Planning Area",
    "population_projection": 54750,
    "existing_licensed_beds": 70,
}

SOUTH_HSA = {
    "code": "HSA-SOUTH",
    "name": "South Planning Area",
    "population_projection": 54748,
    "existing_licensed_beds": 70,
}

ACUTE_FORMULA = {
    "service_type": "ACUTE_CARE_BEDS",
    "effective_from_date": "2026-01-01",
    "use_rate_per_1000": 100.0,
    "average_length_of_stay_days": 5.0,
    "base_target_occupancy_rate": 0.75,
    "high_volume_target_occupancy_rate": 0.85,
    "high_volume_bed_threshold": 100,
}

CYCLE_CALENDAR = {
    "loi_deadline_at": "2026-08-10T00:00:00Z",
    "application_deadline_at": "2026-08-20T00:00:00Z",
    "comment_period_closes_at": "2026-08-25T00:00:00Z",
    "intervention_deadline_at": "2026-08-28T00:00:00Z",
    "completeness_deadline_at": "2026-09-05T00:00:00Z",
    "decision_deadline_at": "2026-09-30T00:00:00Z",
}

# The need figures the canonical planning area and formula produce.
EXPECTED_PROJECTED_PATIENT_DAYS = 27375.0
EXPECTED_PROVISIONAL_REQUIRED_BEDS = 100.0
EXPECTED_SELECTED_OCCUPANCY_RATE = 0.85
EXPECTED_REQUIRED_BEDS_FINAL = 89
EXPECTED_INVENTORY_BEDS_AT_OPEN = 70
EXPECTED_UNMET_BED_NEED_AT_OPEN = 19

# The two reviewers' canonical sheets on application A and their results.
SHEET_REV_1 = {
    "need_conformity_score": 88,
    "financial_feasibility_score": 75,
    "cost_containment_score": 70,
    "access_underserved_score": 90,
    "quality_record_score": 60,
}
SHEET_REV_2 = {
    "need_conformity_score": 91,
    "financial_feasibility_score": 80,
    "cost_containment_score": 65,
    "access_underserved_score": 85,
    "quality_record_score": 62,
}
SHEET_REV_3 = {
    "need_conformity_score": 90,
    "financial_feasibility_score": 78,
    "cost_containment_score": 68,
    "access_underserved_score": 95,
    "quality_record_score": 61,
}
SCORE_ONE_SHEET = 78.65
SCORE_TWO_SHEETS = 79.40
SCORE_THREE_SHEETS = 79.70

# The runner-up application's two sheets and its resulting score.
SHEET_B_REV_1 = {
    "need_conformity_score": 92,
    "financial_feasibility_score": 70,
    "cost_containment_score": 60,
    "access_underserved_score": 80,
    "quality_record_score": 50,
}
SHEET_B_REV_2 = {
    "need_conformity_score": 93,
    "financial_feasibility_score": 71,
    "cost_containment_score": 61,
    "access_underserved_score": 81,
    "quality_record_score": 51,
}

# Decision and issuance clock instants used by the long chains.
DECISION_CLOCK = "2026-09-10T00:00:00Z"
APPEAL_WINDOW_CLOSES = "2026-10-10T00:00:00Z"
ISSUANCE_CLOCK = "2026-10-11T00:00:00Z"

CERTIFICATE_TERMS = {
    "approved_expenditure_limit_cents": 1_000_000_000,
    "implementation_milestone_date": "2027-06-30",
    "expenditure_basis": "CASH",
    "required_completion_pct_at_milestone": 25,
}
EXPECTED_CEILING_CENTS = 1_050_000_000

# Placeholder identifiers used to prove each not-found class.
UNKNOWN_APPLICANT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_HSA_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_CYCLE_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_LOI_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_APPLICATION_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_COMPLETENESS_REVIEW_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_INTERVENTION_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_HEARING_ID = "88888888-8888-4888-8888-888888888888"
UNKNOWN_CERTIFICATE_ID = "99999999-9999-4999-8999-999999999999"
UNKNOWN_APPEAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_FORMULA_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNKNOWN_HEARING_ROOM_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
