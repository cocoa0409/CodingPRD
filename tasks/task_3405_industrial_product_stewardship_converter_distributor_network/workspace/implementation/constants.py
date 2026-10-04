"""Named constants — every value pinned verbatim from SCAFFOLD.yaml `constants:`
and the calculation `constants:` blocks. Each constant is defined exactly once
here and imported everywhere it is used."""

# Logical clock default (PRD §2.4): before any set_current_utc call the clock
# reads exactly this value and never falls back to wall-clock time.
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# Converter authorization gate: quality_audit_score >= 75 (inclusive).
MIN_AUDIT_SCORE = 75

# Lab retest gate: booking from CLOSED_FAIL blocked when failure_count >= 2.
RETEST_MAX_FAILURES = 2

# Lab bench capacity: sum of bench_hours of LAB_BOOKED cases per
# (bench_id, bench_date) must stay <= 8.0 (boundary inclusive).
LAB_BENCH_DAILY_HOURS = 8.0

# Channel price floor margin: distributor worst-case unit price must be
# >= min(reference converter unit price at qty 1) * (1 + 0.08).
CHANNEL_MARGIN_MIN_PCT = 0.08

# Tier discounts (fractions: 0.18 == 18%).
TIER_DISCOUNT_CONVERTER_AUTHORIZED = 0.18
TIER_DISCOUNT_DISTRIBUTOR_PREFERRED = 0.12
TIER_DISCOUNT_STANDARD = 0.0

# Price agreement volume breakpoint array size limit.
MAX_VOLUME_BREAKPOINTS = 3

# Phase-out QUALIFYING -> ENFORCED gate: >= 2 qualified customers (inclusive).
MIN_QUALIFIED_CUSTOMERS = 2

# record-qualification: samples_passed >= 3 (inclusive) qualifies the customer.
QUALIFICATION_MIN_SAMPLES = 3

# Adhesion nominal pass thresholds (N/25mm) by substrate_class.
ADHESION_THRESHOLD_METAL = 15.0
ADHESION_THRESHOLD_POLYMER = 8.0
ADHESION_THRESHOLD_GLASS = 10.0
ADHESION_THRESHOLD_COMPOSITE = 12.0

# Application-derated threshold: +3% per full 10C deviation from 23C.
NOMINAL_TEMP_C = 23
DERATE_PCT_PER_10C = 0.03
