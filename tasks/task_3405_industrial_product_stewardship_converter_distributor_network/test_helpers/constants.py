"""Domain thresholds and pinned literals from PRD §2.4, §3.1-§3.8.

Every value below is stated verbatim in the PRD prose; nothing here is invented.
"""

# PRD §2.4: the logical clock reads exactly 2026-09-01T00:00:00Z before any set call.
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"
# Recipe-nominal clock every fixture drives to first (all recipes start here).
CLOCK_NOMINAL_UTC = "2026-10-01T00:00:00Z"

# PRD §3.3: quality_audit_score must be at least 75 to authorize.
MIN_AUDIT_SCORE = 75

# PRD §3.4: once a case has failed twice, further bookings are rejected.
RETEST_MAX_FAILURES = 2

# PRD §3.4: bench bookings must not exceed 8.0 hours per (bench, date).
LAB_BENCH_DAILY_HOURS = 8.0

# PRD §3.5: distributor floor is the minimum converter unit price raised by 8%.
CHANNEL_MARGIN_MIN_PCT = 0.08

# PRD §3.5: tier discounts.
TIER_DISCOUNT_CONVERTER_AUTHORIZED = 0.18
TIER_DISCOUNT_DISTRIBUTOR_PREFERRED = 0.12
TIER_DISCOUNT_STANDARD = 0.0

# PRD §3.5: volume_breakpoints may hold at most 3 entries.
MAX_VOLUME_BREAKPOINTS = 3

# PRD §3.8: qualified_customer_count must be at least 2 to enforce.
MIN_QUALIFIED_CUSTOMERS = 2

# PRD §3.8: samples_passed at least 3 qualifies a customer.
QUALIFICATION_MIN_SAMPLES = 3

# PRD §3.4: nominal adhesion thresholds (N/25mm) by substrate class.
ADHESION_THRESHOLD_METAL = 15.0
ADHESION_THRESHOLD_POLYMER = 8.0
ADHESION_THRESHOLD_GLASS = 10.0
ADHESION_THRESHOLD_COMPOSITE = 12.0

# PRD §3.4: derating reference temperature and per-step factor.
NOMINAL_TEMP_C = 23
DERATE_PCT_PER_10C = 0.03

# PRD §3.1: review_sla_days defaults to 30 when omitted.
REVIEW_SLA_DAYS_DEFAULT = 30
