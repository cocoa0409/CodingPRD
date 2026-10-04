"""Domain constants — every value transcribed from PRD prose.

Nothing here is invented: the logical-clock default is PRD §2.4, the entry-grid
shape is PRD §2.4/§3.1, the loan pricing tiers and term minimums are PRD §3.4,
the member discount is PRD §3.2, the gallery setup buffer is PRD §3.3, and the
pagination bounds are PRD §2.3.
"""

# ── Logical clock (PRD §2.4) ─────────────────────────────────────────────────
# "At startup — before any clock-setting call — the logical clock reads exactly
# 2026-09-01T00:00:00Z."
CLOCK_STARTUP_DEFAULT_UTC = "2026-09-01T00:00:00Z"
# The clock echo field on both the request and the response.
CLOCK_FIELD = "current_utc"

# ── Quarter-hour entry grid (PRD §2.4) ───────────────────────────────────────
# "A museum entry day runs from 10:00 to 17:30 UTC, divided into thirty
# quarter-hour slots ... slot 0 begins at 10:00 UTC."
ENTRY_DAY_START_HOUR_UTC = 10
SLOT_COUNT_PER_DAY = 30
SLOT_MINUTES = 15
MIN_ENTRY_QUARTER_HOUR = 0
MAX_ENTRY_QUARTER_HOUR = 29
# "Admission carries a grace window of two slots — thirty minutes — beyond the
# reserved slot."
ADMIT_GRACE_SLOTS = 2

# ── Gallery setup buffer (PRD §3.3) ──────────────────────────────────────────
# "Each program occupies its gallery from thirty minutes before its
# start_minute until thirty minutes after its end_minute."
SETUP_BUFFER_MINUTES = 30
MIN_SESSION_MINUTE = 0
MAX_SESSION_MINUTE = 1439

# ── Loan premium tiers (PRD §3.4) ────────────────────────────────────────────
# "the first 100,000,000 cents of declared value price at 0.6 percent, the next
# 400,000,000 cents price at 0.35 percent, and any remainder above those tiers
# prices at 0.15 percent."
TIER1_CAP_CENTS = 100_000_000
TIER1_RATE = 0.006
TIER2_WIDTH_CENTS = 400_000_000
TIER2_RATE = 0.0035
TIER3_RATE = 0.0015
# "a courier surcharge of 12 percent of that rounded base"
COURIER_SURCHARGE_RATE = 0.12
# "a provisional premium: a flat 0.8 percent of declared_value_cents"
PROVISIONAL_FLAT_RATE = 0.008

# ── Loan term gates (PRD §3.4) ───────────────────────────────────────────────
# "an agreement whose declared value is at least 100,000,000 cents requires a
# courier"
COURIER_MIN_DECLARED_VALUE_CENTS = 100_000_000
# "an INDEMNITY agreement requires a declared value of at least 500,000,000
# cents"
INDEMNITY_MIN_DECLARED_VALUE_CENTS = 500_000_000

# ── Member pricing (PRD §3.2) ────────────────────────────────────────────────
# "the exhibition's fee_cents reduced by a member discount of twenty percent,
# rounded half up to whole cents per single ticket"
MEMBER_DISCOUNT_PCT = 0.20

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── PRD worked values (stated verbatim in the PRD; reused by boundary tests) ──
# PRD §3.2: "a fee of 2,500 cents prices at 2,000, a fee of 2,499 prices at
# 1,999, and a fee of 2,501 prices at 2,001."
MEMBER_PRICE_WORKED = {2500: 2000, 2499: 1999, 2501: 2001}
# PRD §3.4: declared 250,000,000 with courier -> FINAL premium 1,260,000 while
# the provisional quote reads 2,000,000.
PREMIUM_WORKED_DECLARED = 250_000_000
PREMIUM_WORKED_FINAL_CENTS = 1_260_000
PREMIUM_WORKED_PROVISIONAL_CENTS = 2_000_000
# PRD §3.4: declared 1,000,075 with courier -> pinned rounding gives 6,720; the
# sum-then-round reading 6,721 is wrong.
PREMIUM_ROUNDING_DECLARED = 1_000_075
PREMIUM_ROUNDING_PINNED_CENTS = 6_720
PREMIUM_ROUNDING_WRONG_CENTS = 6_721
# PRD §2.7: appropriation 1,000,000,000, posted 120,000,000, one approved
# unexecuted acquisition at 300,000,000 -> settled 880,000,000,
# committed 580,000,000; a 700,000,000 expenditure is rejected.
FUND_WORKED_APPROPRIATION = 1_000_000_000
FUND_WORKED_POSTED = 120_000_000
FUND_WORKED_APPROVED_ACQUISITION = 300_000_000
FUND_WORKED_SETTLED = 880_000_000
FUND_WORKED_COMMITTED = 580_000_000
FUND_WORKED_REJECTED_SPEND = 700_000_000

# ── Fixture-default calendar (all dates sit after the clock startup default) ─
# 2026-10-05 is a Monday; 2026-09-07 is a Monday; 2026-09-20 is a Sunday.
DEFAULT_VISIT_DATE = "2026-09-20"
DEFAULT_MONDAY = "2026-10-05"
DEFAULT_LOAN_START_DATE = "2026-10-01"
DEFAULT_LOAN_END_DATE = "2027-01-01"
DEFAULT_MEMBER_PRESALE_OPENS_AT = "2026-09-05T00:00:00Z"
DEFAULT_PUBLIC_SALE_OPENS_AT = "2026-09-10T00:00:00Z"
DEFAULT_RESEARCH_VISIT_START = "2026-10-05"
DEFAULT_RESEARCH_VISIT_END = "2026-10-07"
