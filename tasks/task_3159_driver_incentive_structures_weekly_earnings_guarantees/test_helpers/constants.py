"""Domain thresholds — numeric constants from the PRD calculations (§2, §3)."""

# Logical clock default and well-known time anchors (PRD §2.5)
CLOCK_START = "2026-09-01T00:00:00Z"
# Guarantee week used throughout the design index (Monday 00:00:00Z).
WEEK_START = "2026-09-07T00:00:00Z"
WEEK_END = "2026-09-14T00:00:00Z"
# A point inside the week (Tuesday morning) suitable for completing rides.
WEEK_MID = "2026-09-08T10:00:00Z"

# Rolling-rate window and posture thresholds (PRD §3.2)
RATE_WINDOW_SIZE = 100
ACCEPT_OK_BPS = 9000
ACCEPT_MIN_BPS = 7500
CANCEL_OK_BPS = 1000
CANCEL_MAX_BPS = 2000
MIN_OFFERS = 20

# Fraud posture thresholds (PRD §3.9)
FRAUD_RESTRICT_MIN = 10
FRAUD_WATCH_MIN = 4
FRAUD_DECAY_BUCKET_WEEKS = 4

# Appeal round limits (PRD §3.10)
APPEAL_MAX_INFO_ROUNDS = 2

THRESHOLDS = {
    "RATE_WINDOW_SIZE": RATE_WINDOW_SIZE,
    "ACCEPT_OK_BPS": ACCEPT_OK_BPS,
    "ACCEPT_MIN_BPS": ACCEPT_MIN_BPS,
    "CANCEL_OK_BPS": CANCEL_OK_BPS,
    "CANCEL_MAX_BPS": CANCEL_MAX_BPS,
    "MIN_OFFERS": MIN_OFFERS,
    "FRAUD_RESTRICT_MIN": FRAUD_RESTRICT_MIN,
    "FRAUD_WATCH_MIN": FRAUD_WATCH_MIN,
    "APPEAL_MAX_INFO_ROUNDS": APPEAL_MAX_INFO_ROUNDS,
}
