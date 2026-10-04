"""Domain constants - every value below is pinned by PRD prose.

Sources: logical clock (§2.4), eligibility window and appeal budget (§3.2),
review interval (§3.3), duration gate and separation buffer (§3.4), plan
revision budget (§3.5), wage suspension threshold (§3.6), completion gates,
mastery floor, supervision cadence, conversion and rolling windows (§3.7),
and audit score constants (§3.8).
"""

# §2.4 - the logical clock's startup default; never falls back to wall-clock.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# §3.2 - application eligibility window, both bounds inclusive.
ELIGIBILITY_WINDOW_MIN_DAYS = 30
ELIGIBILITY_WINDOW_MAX_DAYS = 180

# §3.2 - appeal budget per application.
MAX_APPEALS_PER_APPLICATION = 2

# §3.3 - periodic review horizon added at each (re-)authorization / passed review.
REVIEW_INTERVAL_DAYS = 180

# §3.4 - match duration gate.
MIN_INTERNSHIP_DURATION_DAYS = 30
SEPARATION_BUFFER_DAYS = 7

# §3.5 - plan resubmission budget.
MAX_PLAN_REVISIONS = 3

# §3.6 - employer suspension threshold on the wage-violation ledger.
WAGE_VIOLATION_SUSPEND_THRESHOLD = 2

# §3.7 - completion gates.
SUPERVISION_CADENCE_DAYS = 7
MIN_MASTERY_RATIO = 0.75

# §3.7 - conversion and hiring-rate windows.
CONVERSION_WINDOW_DAYS = 90
ROLLING_HIRING_WINDOW_DAYS = 90

# §3.8 - compliance score.
AUDIT_BASE_SCORE = 100.0
SANCTION_SCORE_THRESHOLD = 70
REPEAT_MULTIPLIER = 0.5
SEVERITY_BASE = {"MINOR": 5.00, "MAJOR": 20.00, "CRITICAL": 45.00}
