"""Domain thresholds and monetary constants from the PRD."""

THRESHOLDS = {
    # Risk scoring (PRD §3.3)
    "VELOCITY_REJECT_THRESHOLD": 3,
    "WATCHLIST_POINTS": 8,
    "VELOCITY_POINTS": 8,
    "DOC_FORMAT_POINTS": 4,
    "SELFIE_MISMATCH_POINTS": 5,
    "RISK_REVIEW_THRESHOLD": 15,
    "RISK_BLOCK_THRESHOLD": 20,
    # Kiosk / escort windows
    "KIOSK_ACTIVATION_WINDOW_HOURS": 24,
    "KIOSK_CAPTURE_FAILURE_LIMIT": 3,
    "ESCORT_WINDOW_MINUTES": 15,
    # Lane capacity
    "AMBASSADOR_SEAT_HOURS": 4,
    # Billing
    "PAST_DUE_CANCEL_DAYS": 7,
    # Retention
    "BIOMETRIC_RETENTION_DAYS": 30,
    # Agreement rates
    "MAX_RATE": 0.30,
    # Venue buffer
    "MAX_BUFFER_HOURS": 12,
}

PRICING = {
    # Plan base price in cents (identical for both plans) — PRD §3.4
    "INDIVIDUAL_PRICE_CENTS": 18900,
    "FAMILY_BASE_PRICE_CENTS": 18900,
    "FAMILY_MEMBER_PRICE_CENTS": 9900,
    "FAMILY_SLOTS_TOTAL_DEFAULT": 3,
    "BILLING_PERIOD_DAYS": 30,
}

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
