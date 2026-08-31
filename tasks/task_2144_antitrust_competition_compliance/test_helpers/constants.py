"""Numeric constants the PRD pins for this service."""

# ─── Logical clock ────────────────────────────────────────────────────────
CLOCK_START = "2026-08-01T00:00:00Z"

# ─── Exposure ledger and posture thresholds (PRD §2.8) ────────────────────
THRESHOLDS = {
    "RESTRICTED_EXPOSURE": 40.00,
    "FROZEN_EXPOSURE": 80.00,
    "AGENDA_LEAD_HOURS": 48,
    "COUNSEL_BRIEFING_BUFFER_MINUTES": 60,
    "HSR_WAITING_PERIOD_DAYS": 30,
    "MARKER_VALIDITY_DAYS": 30,
}

# ─── Contact pricing (PRD §3.6) ───────────────────────────────────────────
CONTACT_BASE_POINTS = 4
PRICING_TOPIC_POINTS = 6
RAW_POINTS_CAP = 20
TAG_POINTS_CAP = 5
CHANNEL_POINTS = {
    "IN_PERSON_UNSTRUCTURED": 3,
    "TRADE_SHOW": 2,
    "PHONE": 1,
    "EMAIL": 1,
    "WRITTEN_FORMAL": 0,
}
TAG_POINTS = {
    "CAPACITY": 2,
    "BID": 2,
    "CUSTOMER_ALLOCATION": 3,
    "TERRITORY": 3,
    "STANDARDS": 0,
    "BENCHMARKING": 1,
}
ROLE_POINTS = {"SALES": 2, "PRICING": 3, "LEGAL": 0, "OTHER": 1}
BAND_MULTIPLIER = {"LOW": 1.0, "MODERATE": 1.25, "HIGH": 1.5, "SEVERE": 2.0}
ESCALATION_SURCHARGE_MULTIPLIER = 2.0

# ─── Minutes review pricing (PRD §3.5) ────────────────────────────────────
VERDICT_POINTS = {"CLEAN": 0, "CONCERN": 5, "VIOLATION": 12}
FINDING_POINTS = {
    "PRICING_DISCUSSION": 8,
    "CAPACITY_DISCUSSION": 6,
    "CUSTOMER_ALLOCATION": 10,
    "BID_COORDINATION": 10,
    "MARKET_DATA_AGGREGATE": 1,
    "NONE": 0,
}
FINDING_POINTS_CAP = 15

# ─── Counsel review load (PRD §3.4) ───────────────────────────────────────
REVIEW_BASE_MINUTES = 30
TIER_MINUTES = {"TIER_1_LOW": 0, "TIER_2_MEDIUM": 20, "TIER_3_HIGH": 45}
DENSITY_STEP_MINUTES = 5
DENSITY_STEP_PCT = 25

# ─── Market risk index (PRD §3.3) ─────────────────────────────────────────
INTERACTION_POINT_WEIGHT = 3
INTERACTION_COMPONENT_CAP = 30
OVERLAP_WEIGHT = 0.20
ESCALATED_CONTACT_WEIGHT = 5
FLAGGED_ATTENDANCE_WEIGHT = 3
DOCUMENT_VIOLATION_WEIGHT = 2
INCIDENT_LOAD_CAP = 25

# ─── HSR thresholds, in integer cents (PRD §3.7) ──────────────────────────
HSR_SIZE_OF_TRANSACTION_THRESHOLD_CENTS = 12_000_000_000
HSR_SIZE_OF_TRANSACTION_UPPER_CENTS = 48_000_000_000
HSR_SIZE_OF_PERSON_LARGE_CENTS = 48_000_000_000
HSR_SIZE_OF_PERSON_SMALL_CENTS = 4_800_000_000

# ─── Document audit (PRD §3.8) ────────────────────────────────────────────
HIGH_RISK_PHRASE_PENALTY = 2

# ─── Leniency penalty (PRD §3.9) ──────────────────────────────────────────
DURATION_STEP = 0.10
DURATION_MULTIPLIER_CAP = 2.00
REDUCTION_BY_RANK = {1: 100, 2: 50, 3: 30}

# ─── Defaults used by the payload factories ───────────────────────────────
TEST_DEFAULTS = {
    "EXPOSURE_BUDGET_POINTS": 100,
    "REVIEW_MINUTES_BUDGET": 480,
    "SAMPLE_SIZE": 20,
    "TRAINING_VALIDITY_DAYS": 365,
    "TRAINING_DURATION_MINUTES": 90,
}

# Syntactically valid UUIDs that never resolve to a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-000000000001"
