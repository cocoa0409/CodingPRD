"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted from a PRD sentence that fixes it; nothing is
invented by the test layer.  Generic helpers such as NON_EXISTENT_UUID come
from the runner framework, not from this module.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
# "before any call to that endpoint the logical clock reads exactly
#  2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "DEFAULT_OFFSET": 0,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# ---------------------------------------------------------------------------
# Clock-interval targets (PRD 3.6, 3.7, 3.9)
# ---------------------------------------------------------------------------
INTERVAL_TARGETS = {
    "DTI_TARGET_MIN": 45,          # door_to_imaging_minutes target
    "DTN_TARGET_MIN": 60,          # door_to_needle_minutes target
    "DIDO_TARGET_MIN": 120,        # door_in_door_out_minutes target
    "TELESTROKE_RESPONSE_TARGET_SEC": 300,
}

# ---------------------------------------------------------------------------
# Thrombolytic window classification (PRD 3.2)
# ---------------------------------------------------------------------------
WINDOW_CLASSIFICATION = {
    "LKW_ESTIMATE_MARGIN_MIN": 30,
    "LKW_WINDOW_STANDARD_MIN": 180,
    "LKW_WINDOW_EXTENDED_MIN": 270,
    "WAKEUP_DOOR_WINDOW_MIN": 120,
}

# ---------------------------------------------------------------------------
# Eligibility scoring (PRD 3.5)
# ---------------------------------------------------------------------------
ELIGIBILITY = {
    "INCLUSION_ITEM_POINTS": 15.0,
    "RELATIVE_CONTRAINDICATION_PENALTY": 12.0,
    "ABSOLUTE_CONTRAINDICATION_PENALTY": 100.0,
    "BOARD_CERTIFIED_CREDIT": 6.0,
    "ELIGIBLE_SCORE_MIN": 55.0,
    "OVERRIDE_SCORE_MIN": 40.0,
    "REQUIRED_INCLUSION_ITEM_COUNT": 4,
}

WINDOW_PENALTY_BY_CLASS = {
    "WITHIN_3H": 0.0,
    "WITHIN_4_5H": 8.0,
    "EXTENDED_UNKNOWN": 15.0,
    "OUT_OF_WINDOW": 100.0,
}

REQUIRED_INCLUSION_ITEM_CODES = [
    "INC_ONSET_CONFIRMED",
    "INC_NIHSS_RECORDED",
    "INC_BP_CONTROLLED",
    "INC_ANTICOAG_REVIEWED",
]

# ---------------------------------------------------------------------------
# Video session validity (PRD 3.4)
# ---------------------------------------------------------------------------
VIDEO_SESSION = {
    "MIN_VALID_SESSION_SEC": 180,
    "MAX_SESSION_DISCONNECTS": 2,
}

# ---------------------------------------------------------------------------
# Consult routing (PRD 3.3)
# ---------------------------------------------------------------------------
ROUTING = {
    "CONSULT_DECLINE_LIMIT": 3,
    "NEUROLOGIST_COOLDOWN_MIN": 10,
}

# ---------------------------------------------------------------------------
# EMS routing advisory (PRD 2.9)
# ---------------------------------------------------------------------------
ROUTING_POSTURE = {
    "OPEN_CASE_DIVERT_THRESHOLD": 3,
}

# ---------------------------------------------------------------------------
# Transfer projection (PRD 3.7)
# ---------------------------------------------------------------------------
TRANSFER_PROJECTION = {
    "HANDOFF_PREP_MIN": 20,
    "DRIP_AND_SHIP_EXTRA_MIN": 10,
}

CONGESTION_BY_POSTURE = {
    "ROUTINE": 1.00,
    "DIVERT_ADVISORY": 1.25,
}

REQUIRED_HANDOFF_PACKET_ITEMS = [
    "HP_IMAGING_DISC",
    "HP_LYTIC_RECORD",
    "HP_NIHSS",
    "HP_CONSENT",
]

# "a TRANSFER_ONLY transfer requires that set minus HP_LYTIC_RECORD"
REQUIRED_HANDOFF_PACKET_ITEMS_TRANSFER_ONLY = [
    "HP_IMAGING_DISC",
    "HP_NIHSS",
    "HP_CONSENT",
]

# ---------------------------------------------------------------------------
# Composite certification score (PRD 3.9)
# ---------------------------------------------------------------------------
COMPOSITE = {
    "W_DTN": 0.40,
    "W_DTI": 0.35,
    "W_RESP": 0.25,
    "MAJOR_DEVIATION_PENALTY": 8.0,
    "SENTINEL_DEVIATION_PENALTY": 18.0,
    "DEVIATION_PENALTY_CAP": 24.0,
    "VOLUME_TIER_HIGH": 20,
    "VOLUME_CREDIT_HIGH": 5.0,
    "VOLUME_TIER_MID": 10,
    "VOLUME_CREDIT_MID": 2.0,
    "CERT_SCORE_CERTIFIED_MIN": 85.00,
    "CERT_SCORE_CONDITIONAL_MIN": 70.00,
}

TIER_MULTIPLIER_BY_FACILITY_TYPE = {
    "HUB_PRIMARY": 1.00,
    "SPOKE": 0.95,
    "THROMBECTOMY_CAPABLE": 1.05,
}

# ---------------------------------------------------------------------------
# Report gates (PRD 3.9)
# ---------------------------------------------------------------------------
REPORT_GATES = {
    "MIN_INCLUDED_ABSTRACTIONS": 1,
    "MIN_CLOSED_CASE_VOLUME": 2,
}

# ---------------------------------------------------------------------------
# Deviation review loop (PRD 3.8)
# ---------------------------------------------------------------------------
REVIEW = {
    "MAX_REVIEW_ROUND": 3,
}

# Measure codes that feed a rate field (PRD 3.9)
REPORTED_MEASURE_CODES = ["STK_DTN_60", "STK_DTI_45", "STK_TELESTROKE_RESPONSE"]
