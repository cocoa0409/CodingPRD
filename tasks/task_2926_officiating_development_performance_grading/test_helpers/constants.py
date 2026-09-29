"""Numeric thresholds, weight tables and canonical instants taken from the PRD.

Every symbol here is defined exactly once so that test payloads, fixtures and
assertions all speak about the same value.
"""

# ─── Season program defaults (applied when the create call omits the field) ───

PROGRAM_DEFAULTS = {
    "accuracy_eligibility_threshold": 95.00,
    "min_graded_plays_for_eligibility": 3,
    "appeal_credits_per_official": 3,
    "appeal_window_hours": 72,
    "replay_decision_limit_seconds": 120,
    "reviewable_categories": ["SCORING_PLAY", "TURNOVER", "PLAYER_SAFETY"],
    "max_team_exposures_per_season": 2,
    "min_rest_hours_between_games": 96,
    "travel_lead_hours": 24,
    "crew_size_required": 2,
    "max_application_returns": 2,
    "physical_test_min_score": 70.00,
    "exam_min_score": 80.00,
    "clinic_attendance_required": 1,
}

SEASON_YEAR_MIN = 1900
SEASON_YEAR_MAX = 2999

# ─── Accuracy ─────────────────────────────────────────

ERROR_SCALE = 20.00
ZERO_PLAY_ACCURACY_INDEX = 100.00

# Per-play error points = grade base x impact multiplier x position factor,
# rounded half up to two decimals at the moment the play is written.
GRADE_BASE = {
    "CORRECT": 0.00,
    "INCORRECT_CALL": 1.00,
    "MISSED_CALL": 1.50,
    "INADVERTENT_WHISTLE": 2.00,
}

IMPACT_MULTIPLIER = {
    "LOW": 0.50,
    "MEDIUM": 1.00,
    "HIGH": 1.75,
    "GAME_CRITICAL": 2.50,
}

# Read from the graded official's registered position.
ERROR_POSITION_FACTOR = {
    "REFEREE": 1.20,
    "UMPIRE": 1.00,
    "DOWN_JUDGE": 0.90,
}

# ─── Crew strength ────────────────────────────────────

EXPERIENCE_CAP = 12
GAME_DURATION_HOURS = 4

TIER_WEIGHT = {
    "TIER_1": 1.00,
    "TIER_2": 0.80,
    "TIER_3": 0.60,
}

# Read from the assignment's position, not the official's registered position.
CREW_POSITION_WEIGHT = {
    "REFEREE": 1.30,
    "UMPIRE": 1.00,
    "DOWN_JUDGE": 0.85,
}

EMPTY_CREW_STRENGTH_INDEX = 0.00

# ─── Field evaluation composites and the committee bar ────

W_MECHANICS = 0.40
W_RULES = 0.35
W_PRESENCE = 0.25

MIN_EVALUATIONS = 2
MIN_EVAL_AVERAGE = 75.00

MIN_EXPERIENCE_FOR_TIER_2 = 5
MIN_EXPERIENCE_FOR_TIER_1 = 8
ADVANCEMENT_MIN_ACCURACY = 90.00

# ─── Retention ────────────────────────────────────────

W_ACCURACY = 0.70
W_AVAILABILITY = 0.30

BAND_HIGH_FLOOR = 90.00
BAND_MID_FLOOR = 80.00
PENALTY_HIGH = 2.00
PENALTY_MID = 5.00
PENALTY_LOW = 9.00

RETAIN_FLOOR = 90.00
DEVELOP_FLOOR = 75.00
SCORE_FLOOR = 0.00

AVAILABILITY_DIVISOR_FLOOR = 1

# ─── Discipline ───────────────────────────────────────

REMEDIATION_CYCLE_CAP = 2

# ─── Score range and pagination ───────────────────────

SCORE_MIN = 0.00
SCORE_MAX = 100.00

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── The logical clock ────────────────────────────────

CLOCK_START = "2026-08-01T00:00:00.000Z"

# Canonical instants the fixtures pin the clock to.
INSTANT_SEASON_START = "2026-08-01T00:00:00.000Z"
INSTANT_G1_KICKOFF = "2026-09-13T17:00:00.000Z"
INSTANT_G1_REPLAY_OPEN = "2026-09-13T18:00:00.000Z"
INSTANT_G1_POSTGAME = "2026-09-13T21:30:00.000Z"

# The occupancy window a 17:00 kickoff on 13 September 2026 yields under the
# default travel lead of 24 hours and rest period of 96 hours.
INSTANT_G1_OCCUPIED_FROM = "2026-09-12T17:00:00.000Z"
INSTANT_G1_OCCUPIED_UNTIL = "2026-09-17T21:00:00.000Z"

# A second game, five days later, whose window opens exactly on the instant the
# first game's window closes.
INSTANT_G2_KICKOFF = "2026-09-18T21:00:00.000Z"
INSTANT_G2_POSTGAME = "2026-09-19T01:30:00.000Z"
INSTANT_G2_KICKOFF_MINUS_1MIN = "2026-09-18T20:59:00.000Z"

# That second game's own occupancy window: its start lands exactly on the first
# game's close, and its close lands exactly on the third game's start.
INSTANT_G2_OCCUPIED_FROM = "2026-09-17T21:00:00.000Z"
INSTANT_G2_OCCUPIED_UNTIL = "2026-09-23T01:00:00.000Z"

INSTANT_G4_KICKOFF = "2026-09-19T17:00:00.000Z"
INSTANT_G3_KICKOFF = "2026-09-24T01:00:00.000Z"

# 72 hours after a grade posted at the postgame instant, and one second later.
INSTANT_APPEAL_DEADLINE = "2026-09-16T21:30:00.000Z"
INSTANT_PAST_APPEAL_DEADLINE = "2026-09-16T21:30:01.000Z"

# A 120-second replay window opened at 18:00:00, its close instant, and the
# second after it.
INSTANT_REPLAY_WINDOW_CLOSE = "2026-09-13T18:02:00.000Z"
INSTANT_PAST_REPLAY_WINDOW_CLOSE = "2026-09-13T18:02:01.000Z"

# A decision recorded 60 seconds into that window, and a second attempt 30
# seconds after it.
INSTANT_REPLAY_DECIDE_AT_60S = "2026-09-13T18:01:00.000Z"
INSTANT_REPLAY_RETRY_AT_90S = "2026-09-13T18:01:30.000Z"

# A midseason instant the clock setter is moved to, well after the default.
INSTANT_MIDSEASON_CLOCK_SET = "2026-08-15T09:30:00.000Z"

# The day after the game, for a publication that supersedes an earlier one.
INSTANT_NEXT_DAY_PUBLISH = "2026-09-14T15:00:00.000Z"

# Three successive open instants on a second booth, spaced so that the second
# window overlaps the first and the third overlaps both.
INSTANT_BOOTH_B_FIRST_OPEN = "2026-09-13T18:03:00.000Z"
INSTANT_BOOTH_B_SECOND_OPEN = "2026-09-13T18:04:00.000Z"
INSTANT_BOOTH_B_THIRD_OPEN = "2026-09-13T18:04:30.000Z"

# ─── Test data literals ───────────────────────────────

UNKNOWN_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

TEST_DEFAULTS = {
    "season_year": 2026,
    "home_team_code": "MIA",
    "away_team_code": "BUF",
    "venue_market_code": "MIA",
    "station_code": "BOOTH-1",
    "basis_note": "The camera angle supports the no-call on this play.",
    "report_body": "Pool report on the graded play cited above.",
    "remediation_plan": "Two rules clinics and a film review session.",
}
