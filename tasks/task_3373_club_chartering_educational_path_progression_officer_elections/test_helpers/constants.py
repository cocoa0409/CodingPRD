"""Domain thresholds and fixture defaults for the Club Chartering Path Progression API.

Every numeric constant below is stated in the PRD (dues quote lines, proration
midpoint, score bands, overlap buffer, rotation window, slot capacity, quorum
and roster minimums).
"""

# --- Dues quote (PRD §3.2) ---
INTL_DUES_CENTS = 4500
DISTRICT_LEVY_RATE = 0.075
NEW_MEMBER_FEE_CENTS = 2000
REINSTATEMENT_FEE_CENTS = 1000
LATE_FEE_RATE = 0.05
CYCLE_HALF_DAYS = 91

# --- Good-standing score and recognition points (PRD §2.7) ---
WEIGHT_DUES = 30
WEIGHT_OFFICER = 25
WEIGHT_EDUCATION = 20
WEIGHT_MEETING = 15
WEIGHT_DCP = 10
REQUIRED_MEMBER_COUNT = 20
OFFICER_TRAINED_TARGET = 4
EDUCATION_TARGET = 4
MEETINGS_TARGET = 6
DCP_TARGET = 5
GOOD_MIN = 80
PROBATION_MIN = 60
REVOKE_BELOW = 40

DCP_EDUCATION_POINT_CAP = 6
DCP_TOTAL_POINT_CAP = 10
DCP_PRESIDENT_TIER_MIN = 9
DCP_SELECT_TIER_MIN = 7
DCP_DISTINGUISHED_TIER_MIN = 5

# --- Education level requirement table (PRD §3.4) ---
LEVEL_REQUIREMENTS = {
    1: {"speeches": 2, "projects": 2},
    2: {"speeches": 1, "projects": 2},
    3: {"speeches": 1, "projects": 2},
    4: {"speeches": 1, "projects": 1},
    5: {"speeches": 1, "projects": 1},
}
MAX_PROJECTS_PER_LEVEL = 6

# --- Meetings and role rotation (PRD §3.6) ---
MEETING_BUFFER_MINUTES = 30
DEFAULT_MEETING_MINUTES = 90
REQUIRED_ROLE_SLOTS = 7
MAX_SPEECH_ROLES_PER_WINDOW = 2
SPEECH_WINDOW_DAYS = 7
QUORUM_ATTENDANCE_MIN = 5

# --- Contests (PRD §3.8) ---
BALLOTS_REQUIRED_FOR_JUDGED = 3
BALLOT_CONTENT_WEIGHT = 0.5
BALLOT_DELIVERY_WEIGHT = 0.3
BALLOT_LANGUAGE_WEIGHT = 0.2
SCORE_MIN = 0
SCORE_MAX = 100

# --- Officer terms (PRD §3.7) ---
TRAINING_DUE_DAYS = 30

# --- Coaching queue (PRD §3.9) ---
COACHING_QUEUE_LIMIT = 100

# --- Fixture defaults ---
TEST_CLUB_NAME = "Riverside Voices"
TEST_CLUB_NAME_ALT = "Lakeview Speakers"
TEST_CLUB_NAME_JUDGE = "Harbor Masters"
TEST_CLUB_DUES_CENTS = 3000
TEST_VENUE_NAME = "Riverside Library"
TEST_DISTRICT_NUMBER = "42"
TEST_DIVISION_CODE = "C"
TEST_AREA_CODE = "C-3"

# A first dues cycle that opened well before every join_date used by the fixtures,
# so no fixture accidentally lands in the proration half of the cycle.
CYCLE_OPENED_AT = "2026-09-01T00:00:00Z"
JOIN_DATE = "2026-09-02T00:00:00Z"
# cycle_opened_at + 91 days: the first instant that prorates (PRD §2.5).
PRORATION_CUTOFF_AT = "2026-12-01T00:00:00Z"
ORGANIZING_MEETING_AT = "2026-09-05T18:30:00Z"
ORGANIZING_MEETING_ATTENDEES = 9
FIRST_CYCLE_CLOSE_AT = "2026-10-01T00:00:00Z"
SECOND_CYCLE_OPENED_AT = "2027-04-01T00:00:00Z"
MEETING_AT = "2026-09-10T18:30:00Z"
CONTEST_AT = "2026-10-15T18:30:00Z"
VISIT_AT = "2026-09-20T18:30:00Z"

# Quote totals for the fixture club dues of 3000 cents (PRD §3.2 pinned order).
QUOTE_3000_FIRST_TIME = 10063
QUOTE_2999_FIRST_TIME = 10062
QUOTE_2999_FIRST_TIME_SUM_THEN_ROUND = 10061
QUOTE_2999_REINSTATEMENT = 9515
