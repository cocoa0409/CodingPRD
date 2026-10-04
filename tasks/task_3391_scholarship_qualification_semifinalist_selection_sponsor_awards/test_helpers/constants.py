"""Domain constants — every rule value copied verbatim from PRD.md.

Two groups:
- Rule constants (CLOCK_START_ISO, SECTION_*, MIN_STATE_SLOTS, ...): each is a
  literal stated in PRD prose and cited below by section.
- TEST_DEFAULTS: canonical scenario fixture values (not PRD rules) shared by
  the common setup chains so factories stay consistent.
"""

# --- Logical clock (PRD §2.5: "the logical clock starts at exactly
#     2026-09-01T00:00:00Z") ---
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Preliminary examination scoring (PRD §3.4: "each an integer from 8 to 38
#     inclusive"; "the sum of the three section scores multiplied by the
#     section weight 2, giving an exact integer in the range 48 to 228") ---
SECTION_WEIGHT = 2
SECTION_SCORE_MIN = 8
SECTION_SCORE_MAX = 38
SELECTION_INDEX_MIN = 48
SELECTION_INDEX_MAX = 228

# --- Semifinalist slot apportionment (PRD §3.2: "the minimum state guarantee
#     MIN_STATE_SLOTS (exactly 1)"; quota "stored rounded half up to 4 decimal
#     places") ---
MIN_STATE_SLOTS = 1
QUOTA_DECIMAL_PLACES = 4

# --- Award lifecycle (PRD §3.7: "acceptance_deadline computed 30 days after
#     offered_logical_at"; PRD §3.8: "term i takes a scheduled_date of T0 plus
#     (i - 1) times 180 days") ---
ACCEPTANCE_WINDOW_DAYS = 30
TERM_INTERVAL_DAYS = 180

# --- Notifications (PRD §3.9: "at least 2 days past the most recent
#     released_logical_at"; "SEMIFINALIST_NOTICE is 1, FINALIST_NOTICE is 2,
#     AWARD_OFFER is 3, and PUBLIC_ANNOUNCEMENT is 4") ---
PUBLICITY_GAP_DAYS = 2
NOTIFICATION_SEQUENCE = {
    "SEMIFINALIST_NOTICE": 1,
    "FINALIST_NOTICE": 2,
    "AWARD_OFFER": 3,
    "PUBLIC_ANNOUNCEMENT": 4,
}

# --- Renewal verification (PRD §3.8: "a reported_gpa of at least 2.5";
#     PRD §3.5: "gpa_scaled on a 0.0 to 4.0 scale") ---
RENEWAL_MIN_GPA = 2.5
GPA_MIN = 0.0
GPA_MAX = 4.0

# --- Confirming examination floor bounds (PRD §3.1: "an integer from 48 to
#     228 inclusive") ---
CONFIRMING_INDEX_MIN = 48
CONFIRMING_INDEX_MAX = 228

# --- Pagination (PRD §2.3: "limit (default 10, minimum 1, maximum 100) and
#     offset (default 0)") ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Canonical scenario fixture values (test defaults, not PRD rules) ---
TEST_DEFAULTS = {
    # ProgramCycle
    "TARGET_GRADUATION_YEAR": 2028,
    "TOTAL_SEMIFINALIST_SLOTS": 5,
    "NATIONAL_AWARD_SLOTS": 0,
    "NATIONAL_AWARD_AMOUNT_CENTS": 250000,
    "CONFIRMING_FLOOR": 200,
    "APPLICATION_DEADLINE": "2027-12-15T00:00:00Z",
    "SEMIFINALIST_EMBARGO_UNTIL": "2027-09-10T00:00:00Z",
    "FINALIST_EMBARGO_UNTIL": "2028-02-10T00:00:00Z",
    "AWARD_EMBARGO_UNTIL": "2028-03-01T00:00:00Z",
    "PUBLIC_EMBARGO_UNTIL": "2028-03-01T00:00:00Z",
    "STATE_CODE": "ZZ",
    "STATE_POPULATION": 10000,
    # Entry scoring: (37, 37, 38) -> selection_index 224
    "SCORE_READING": 37,
    "SCORE_WRITING": 37,
    "SCORE_MATH": 38,
    # FinalistApplication
    "CONFIRMING_SELECTION_INDEX": 210,
    "GPA_SCALED": 3.9,
    "COURSE_RIGOR": "MOST_RIGOROUS",
    # SponsorAgreement window and pool
    "AGREEMENT_AWARD_AMOUNT_CENTS": 250000,
    "AGREEMENT_MAX_AWARDS": 2,
    "AGREEMENT_POOL_TOTAL_CENTS": 500000,
    "AGREEMENT_WINDOW_START": "2027-01-01",
    "AGREEMENT_WINDOW_END": "2027-12-31",
    # CollegeInstitution sponsorship configuration
    "COLLEGE_AWARD_AMOUNT_CENTS": 100000,
    "COLLEGE_RENEWABLE_YEARS_TOTAL": 2,
    "COLLEGE_TERMS_PER_YEAR": 1,
    "COLLEGE_POOL_TOTAL_CENTS": 500000,
    "COLLEGE_MAX_AWARDS": 5,
    # RenewalVerification report
    "RENEWAL_ACADEMIC_YEAR_INDEX": 2,
    "RENEWAL_REPORTED_ENROLLMENT": "FULL_TIME",
    "RENEWAL_REPORTED_GPA": 3.5,
}

__all__ = [
    "CLOCK_START_ISO",
    "SECTION_WEIGHT",
    "SECTION_SCORE_MIN",
    "SECTION_SCORE_MAX",
    "SELECTION_INDEX_MIN",
    "SELECTION_INDEX_MAX",
    "MIN_STATE_SLOTS",
    "QUOTA_DECIMAL_PLACES",
    "ACCEPTANCE_WINDOW_DAYS",
    "TERM_INTERVAL_DAYS",
    "PUBLICITY_GAP_DAYS",
    "NOTIFICATION_SEQUENCE",
    "RENEWAL_MIN_GPA",
    "GPA_MIN",
    "GPA_MAX",
    "CONFIRMING_INDEX_MIN",
    "CONFIRMING_INDEX_MAX",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MIN",
    "PAGE_LIMIT_MAX",
    "PAGE_OFFSET_DEFAULT",
    "TEST_DEFAULTS",
]
