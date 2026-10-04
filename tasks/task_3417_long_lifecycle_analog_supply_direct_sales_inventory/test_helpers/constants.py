"""Fixture date literals shared by helpers and tests.

Every value is derived from the PRD's declared logical clock and window rules,
never from wall-clock time:

- PRD §2.5: before any client call the clock starts at exactly
  2026-09-01T00:00:00Z and never falls back to wall-clock time.
- PRD §3.3: a schedule prices quotes only once `effective_from` is at or before
  the current clock reading.
- PRD §2.5: a capacity pool is OPEN from `period_start` (inclusive) up to but
  excluding `period_end`.
- PRD §3.7: `last_order_date` >= `notice_date` + 180 days and
  `last_ship_date` >= `last_order_date` + 90 days.
- PRD §2.5 / §3.8: an ACTIVE design win completes once the clock reaches
  `start_date` plus four years; recognition counts complete twelve-month
  anniversaries.
"""

# Pricing schedule effective date that precedes the default clock, so a freshly
# published schedule is already effective for quotes and submits (PRD §3.3).
PRICING_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"

# Capacity pool window that is OPEN at the default clock (inclusive start,
# PRD §2.5): [2026-09-01, 2026-12-01).
POOL_PERIOD_START = "2026-09-01T00:00:00Z"
POOL_PERIOD_END = "2026-12-01T00:00:00Z"

# Canonical EOL notice window anchored at the default clock (PRD §3.7 floors):
# 2026-09-01 + 180 days = 2027-02-28; 2027-02-28 + 90 days = 2027-05-29.
EOL_NOTICE_DATE = "2026-09-01T00:00:00Z"
EOL_LAST_ORDER_DATE = "2027-02-28T00:00:00Z"
EOL_LAST_SHIP_DATE = "2027-05-29T00:00:00Z"

# Design-win start date used by fixtures (PRD §3.8): its first twelve-month
# anniversary is 2028-01-01; a clock reading of 2028-06-01 yields exactly one
# elapsed anniversary.
DESIGN_WIN_START_DATE = "2027-01-01T00:00:00Z"
DESIGN_WIN_ONE_YEAR_CLOCK = "2028-06-01T00:00:00Z"
