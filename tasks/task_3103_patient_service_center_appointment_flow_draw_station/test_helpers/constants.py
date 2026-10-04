"""Domain thresholds and fixture anchors for the patient service center API."""

# ─── Operational constants named in the PRD ───────────────────────────────────
CONSTANTS = {
    # Queue / wait estimate (§3.3)
    "BAND_IMMEDIATE_MAX": 10,
    "BAND_WITHIN_WINDOW_MAX": 30,
    "HEAP_FLAG_PERIOD_MINUTES": 90,
    # Fasting (§3.1, §3.8)
    "FASTING_MIN_HOURS": 8,
    # Check-in window (§3.3)
    "EARLY_CHECKIN_MINUTES": 30,
    "GRACE_MINUTES": 15,
    # Courier (§2.10, §3.6)
    "CHECKIN_LEAD_MINUTES": 30,
    "CHECKIN_GRACE_MINUTES": 0,
    "WINDOW_MINUTES": 720,
    "COMMIT_LEAD_MINUTES": 1080,
    "COMMIT_INTERVAL_MINUTES": 60,
    "CUTOFF_BEFORE_DISPATCH_MINUTES": 15,
    "MAX_SPECIMENS_PER_RUN": 40,
    # Specimen stability (§2.10)
    "STABILITY_FACTOR": 1.0,
    # Rejection (§3.7)
    "DAY_CAP": 3,
    "REPEAT_WINDOW_HOURS": 24,
    # Draw attempts (§3.4)
    "MAX_TOTAL_ATTEMPTS": 2,
    "SAME_DAY_MINUTES_SINCE_FIRST": 60,
    # Abandonment (§3.3)
    "MAX_CALL_WAIT_MINUTES": 30,
    # Pricing (§3.5)
    "ATTENDED_COLLECTED_DISCOUNT": 0.20,
    "PEDIATRIC_FEE_MULTIPLIER": 1.10,
    "EXPIRED_PLAN_DISCOUNT_PCT": 0.20,
    # Booking horizon (§2.9)
    "MAX_FUTURE_BOOKING_MINUTES": 10080,
    # Pediatric age offset (§3.1)
    "PEDIATRIC_AGE_MAX_YEARS": 18,
}

THRESHOLDS = CONSTANTS

# ─── Reference fixture values (the seeded reference plan and grid) ────────────
REFERENCE_PLAN = {
    "payer_name": "HORIZON HMO",
    "plan_type": "HMO",
    "copay_cents": 2500,
    "coinsurance_pct": 0.25,
    "deductible_remaining_cents": 0,
    "allowed_amount_cents": 10000,
    "prior_paid_pct": 0.0,
}

# Calibration-safe center fixture values.
CENTER_DEFAULTS = {
    "name": "Aurora Draw Station",
    "state_code": "TX",
    "timezone_offset_minutes": -300,
    "station_count": 2,
    "slot_minutes": 15,
    "open_local_minutes": 480,
    "close_local_minutes": 1020,
    "pediatric_capable": True,
    "draw_hold_minutes": 30,
}

# ─── Time anchors used across fixtures and tests ──────────────────────────────
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_MORNING = "2026-09-01T13:00:00Z"
CLOCK_WINDOW = "2026-09-01T13:30:00Z"

TEST_DEFAULTS = {
    "list_price_cents": 5000,
    "shift_start_local_minutes": 420,
    "shift_end_local_minutes": 1020,
    "slot_span": 1,
}