"""Domain thresholds and constants.

Every value below is copied verbatim from the PRD; the trailing comment on
each names the PRD section and quote it was taken from. Never invent a value
here — if the PRD does not state it, it does not belong in this file.
"""

# ─── Platform / clock (PRD section 2.4) ──────────────

API_PREFIX = "/identity-protection"
# PRD section 2.4: "This endpoint is deliberately mounted outside the API
# prefix at exactly `/_clock/set_current_utc` — it is not under
# `/identity-protection`."
CLOCK_PATH = "/_clock/set_current_utc"
# PRD section 2.4: "At server startup the logical clock is exactly
# `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time"
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ─── Pagination (PRD section 2.3) ────────────────────
# "The `limit` parameter caps the number of items returned: it defaults to 10,
# with a minimum of 1 and a maximum of 100. The `offset` parameter skips a
# number of items from the start of the result set and defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ─── Tax year / filing deadline (PRD sections 3.4, 3.8) ──
# PRD section 3.4: "the `tax_year` (this deployment serves tax year 2026; any
# other value is rejected with `ERR_INVALID_REQUEST`)"
DEFAULT_TAX_YEAR = 2026
# PRD section 3.8: "for tax year 2026, that deadline is 2027-04-15"
FILING_DEADLINE_BY_TAX_YEAR = {2026: "2027-04-15"}

# ─── Filter risk score (PRD section 3.4) ─────────────
# "divides it into whole steps of 100000 cents (that is, $1,000 per step)
# using floor division"
REFUND_DELTA_STEP_CENTS = 100000
# "and caps the result at 3 steps"
MAX_DELTA_STEPS = 3
# "The raw sum is clamped to an integer score no lower than 0 and no higher
# than 100, the score cap."
SCORE_CAP = 100
SCORE_FLOOR = 0

# ─── Refund interest (PRD section 3.8) ───────────────
# "an interest-free window of 45 days after the anchor, an annual rate of 7.0
# percent, and a 365-day year basis"
INTEREST_FREE_DAYS = 45
ANNUAL_RATE_PCT = 7.0
DAY_COUNT_BASIS = 365

# ─── Scheme detection scans (PRD section 3.7) ────────
# "by `received_at` against the current logical clock, over the trailing
# 7-day window ending now, with both window bounds inclusive"
VELOCITY_WINDOW_DAYS = 7
# "When the count reaches at least 10 — a count of exactly 10 fires"
VELOCITY_THRESHOLD = 10
# "When that distinct-taxpayer count reaches at least 3 — exactly 3 fires"
ROUTING_THRESHOLD = 3

# ─── Dependent credit (PRD sections 3.4, 3.6) ────────
# PRD section 3.4: "Every claim's `credit_cents` is fixed at 200000 cents —
# the dependent credit at stake"
DEPENDENT_CREDIT_CENTS = 200000

# ─── Identity verification (PRD section 3.5) ─────────
# "The third failure is terminal and severe: with `attempts_count` reaching
# its maximum of 3, the case lands in `EXPIRED`"
MAX_VERIFICATION_ATTEMPTS = 3
# "Its `deadline_at` is set to 30 days after creation by the logical clock"
CASE_DEADLINE_DAYS = 30
# PRD section 3.9: "seven days from now by the logical clock"
EXPEDITED_CASE_DEADLINE_DAYS = 7
# "an `ONLINE` case requires `PHOTO_ID` and `PRIOR_YEAR_RETURN`; a `PHONE`
# case requires `PHOTO_ID` and `SSA_CARD`; an `IN_PERSON` case requires
# `PHOTO_ID` and `UTILITY_BILL`"
REQUIRED_DOCS_BY_CHANNEL = {
    "ONLINE": ["PHOTO_ID", "PRIOR_YEAR_RETURN"],
    "PHONE": ["PHOTO_ID", "SSA_CARD"],
    "IN_PERSON": ["PHOTO_ID", "UTILITY_BILL"],
}

# ─── Theft report review window (PRD section 3.3) ────
# "the closed review window that runs from the earlier report's `created_at`
# through 60 days later, both endpoints inclusive"
REPORT_REVIEW_WINDOW_DAYS = 60

# ─── Dependent conflict evidence window (PRD section 3.6) ──
# "sets an `evidence_window_ends_at` exactly 30 days after the conflict's
# creation"
EVIDENCE_WINDOW_DAYS = 30

# ─── OCC guard field (PRD section 2.7) ───────────────
# "Each of these requests must carry `expected_taxpayer_version`"
OCC_FIELD = "expected_taxpayer_version"
