"""Domain constants for the municipal rulemaking / disclosure / dealer-compliance API.

Every value here is copied verbatim from PRD.md (the contract the implementation
is built against). Nothing is invented; a number that cannot be traced to the
PRD does not belong in this module.
"""

# --- Routing ---------------------------------------------------------------

# All business resources are mounted under this prefix (PRD section 4). The
# logical-clock endpoint is mounted OUTSIDE it, exactly as listed there.
API_PREFIX = "/msrb"

# --- Logical clock (PRD section 2.4) ----------------------------------------

# On a fresh deployment, before any clock-setting call, the logical clock
# starts at exactly this instant - never the wall clock.
CLOCK_START = "2026-09-01T00:00:00Z"

# --- Trade reporting (PRD section 3.5) ---------------------------------------

# Fifteen-minute reporting limit, measured in whole seconds. A gap of exactly
# 900 seconds is timely; the late comparison is strictly-greater.
TRADE_REPORT_LIMIT_SECONDS = 900

# Price-transparency banding: the disseminated size is the smaller of the
# par amount and this cap; the cap flag is true exactly when par exceeds it.
LARGE_TRADE_PAR_CAP = 5_000_000

# Dealer compliance posture: the late tally counts late, still-disseminated
# reports whose receipt falls inside the trailing thirty-day half-open window
# (a report received exactly thirty days ago is excluded). The posture becomes
# WATCH when the count reaches five; the fifth late report trips the threshold,
# boundary inclusive.
LATE_TRADE_WINDOW_DAYS = 30
LATE_WATCH_THRESHOLD = 5

# --- Rule effectiveness (PRD section 3.2) ------------------------------------

# effective_at = approval_at + delay, where the delay is selected by the
# expedited flag captured at comment-opening time.
STANDARD_EFFECTIVENESS_DELAY_DAYS = 30
EXPEDITED_EFFECTIVENESS_DELAY_DAYS = 10

# --- Comment windows (PRD section 3.1) ---------------------------------------

# comment_period_days must be at least 21 and at most 90; both ends inclusive.
COMMENT_PERIOD_MIN_DAYS = 21
COMMENT_PERIOD_MAX_DAYS = 90

# --- Examinations (PRD section 3.6) ------------------------------------------

# Inclusive pass marks: a score equal to the mark is a PASS.
PASS_SCORES = {"MSRB_50": 70, "MSRB_52": 72, "MSRB_53": 75, "MSRB_54": 80}

# Series a registration class must pass (at least one PASS each) to qualify.
REQUIRED_SERIES = {
    "MUNICIPAL_ADVISOR_REP": ["MSRB_50"],
    "MUNICIPAL_DEALER_REP": ["MSRB_52"],
    "MUNICIPAL_PRINCIPAL": ["MSRB_53", "MSRB_54"],
}

# Retake exclusion: a prior attempt on the same (professional, series) pair
# blocks a new attempt while it is strictly younger than thirty days; a prior
# attempt exactly thirty days old does not block (half-open window).
RETAKE_WINDOW_DAYS = 30

# --- Continuing education (PRD section 3.6) -----------------------------------

# Cycle anchors: ce_cycle_end = qualified_at + 365 days;
# ce_grace_end = ce_cycle_end + 60 days.
CE_CYCLE_DAYS = 365
CE_GRACE_DAYS = 60

# Cure thresholds while CE_DUE; both bind independently (inclusive >=).
CE_TOTAL_REQUIRED = 12
CE_ETHICS_REQUIRED = 2

# --- Event notices (PRD section 3.4) ------------------------------------------

# Whole calendar days between the UTC date of the event and the UTC date of
# filing; filing on exactly the tenth day is TIMELY (inclusive boundary).
EVENT_NOTICE_LIMIT_DAYS = 10

# --- Fiduciary solicitation cap (PRD section 3.8) -----------------------------

# CONTINGENT compensation may not exceed 25,000 dollars, carried as cents.
# Exactly the cap is permitted; one cent above it is rejected.
FIDUCIARY_FEE_CAP_CENTS = 2_500_000

# --- Market-data subscription fees (PRD section 3.7) --------------------------

# Monthly fee = round_half_up(
#     (BASE + max(seats - INCLUDED, 0) * PER_SEAT) * SCOPE * ORG_TYPE_DISCOUNT
# ), rounded exactly once at the end. The annual invoice is twelve times the
# stored (already rounded) monthly fee - round per line, then sum.
SUBSCRIPTION_BASE_CENTS = {
    "TRADE_REALTIME": 250_000,
    "TRADE_HISTORICAL": 99_999,
    "DISCLOSURE_ARCHIVE": 150_000,
}
SUBSCRIPTION_PER_SEAT_CENTS = {
    "TRADE_REALTIME": 5_000,
    "TRADE_HISTORICAL": 2_500,
    "DISCLOSURE_ARCHIVE": 1_000,
}
SUBSCRIPTION_INCLUDED_SEATS = {
    "TRADE_REALTIME": 5,
    "TRADE_HISTORICAL": 10,
    "DISCLOSURE_ARCHIVE": 20,
}
LICENSE_SCOPE_MULTIPLIER = {
    "INTERNAL": 1.0,
    "DISPLAY": 1.5,
    "REDISTRIBUTION": 2.25,
}
ORG_TYPE_DISCOUNT = {
    "ISSUER": 1.0,
    "OBLIGATED_PERSON": 1.0,
    "BROKER_DEALER": 1.0,
    "MUNICIPAL_ADVISOR": 0.9,
}
MONTHS_PER_YEAR = 12

# --- Pagination (PRD section 2.3) ---------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
