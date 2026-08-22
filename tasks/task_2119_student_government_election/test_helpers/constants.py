"""Domain thresholds and the instants the logical election clock is driven to.

Nothing in this system reads the host's wall clock; before the first clock call
the clock reads exactly 2026-08-01T00:00:00Z (PRD §2.4).
"""

# ─── Compliance scoring (PRD §3.5) ────────────────────────────────────────────

PENALTY_BASE = {"MINOR": 5, "MAJOR": 15, "SEVERE": 40}
REPEAT_STEP = 0.5
VOTING_WINDOW_FACTOR = 1.5
OVERSPEND_CENTS_PER_POINT = 1000
OVERSPEND_POINTS_CAP = 25
PENALTY_POINTS_MAX = 100
DISQUALIFICATION_POINT_THRESHOLD = 60

# ─── Venue geometry (PRD §2.10) ───────────────────────────────────────────────

TEARDOWN_BUFFER_MINUTES = 30

# ─── Logical clock instants ───────────────────────────────────────────────────

CLOCK_EPOCH = "2026-08-01T00:00:00Z"
PETITION_DEADLINE = "2026-09-01T00:00:00Z"
AT_PETITION_DEADLINE = "2026-09-01T00:00:00Z"
VOTING_OPENS_AT = "2026-09-15T09:00:00Z"
VOTING_CLOSES_AT = "2026-09-16T17:00:00Z"
INSIDE_VOTING_WINDOW = "2026-09-15T10:00:00Z"
LATER_INSIDE_VOTING_WINDOW = "2026-09-15T11:00:00Z"
AFTER_VOTING_WINDOW = "2026-09-16T18:00:00Z"
TERM_START_DATE = "2026-10-01T00:00:00Z"
TERM_END_DATE = "2027-05-31T00:00:00Z"
AFTER_TERM_START = "2026-10-02T00:00:00Z"

# ─── Opaque operator identifiers ──────────────────────────────────────────────
# The three administrative roles carry opaque identities not tied to any
# persisted entity (PRD §2.1).

COMMISSIONER_ID = "commissioner-1"
REGISTRAR_ID = "registrar-1"
ADVISOR_ID = "advisor-1"
SECOND_ADVISOR_ID = "advisor-2"

# ─── Test defaults ────────────────────────────────────────────────────────────

TEST_DEFAULTS = {
    "ELECTION_TITLE": "Fall 2026 SGA General",
    "ACADEMIC_YEAR": "2026-2027",
    "SPENDING_CAP_CENTS": 50_000,
    "LARGE_SPENDING_CAP_CENTS": 500_000,
    "POSTER_CAP": 50,
    "LARGE_POSTER_CAP": 100,
    "QUORUM_PCT": 25.00,
    "RUNOFF_THRESHOLD_PCT": 50.00,
    "OFFICE_NAME": "President",
    "SENATE_OFFICE_NAME": "Student Senate",
    "APPROVAL_THRESHOLD_PCT": 66.67,
    "REQUIRED_TRAINING_MODULES": 3,
}

# A well-formed identifier that matches no row in any collection.
NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"

ALL_CLASS_YEARS = ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR", "GRADUATE"]
UNDERGRADUATE_CLASS_YEARS = ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"]
