"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    "MIN_AGE": 45,
    "MAX_AGE": 75,
    "KIT_ABANDON_DAYS": 45,
    "RECOLLECTION_ABANDON_DAYS": 30,
    "MAX_RECOLLECTIONS": 2,
    "STABILIZATION_HOURS": 72,
    "NAVIGATION_WINDOW_DAYS": 90,
    "ADHERENCE_WINDOW_DAYS": 365,
    "REMINDER_OFFSET_1": 7,
    "REMINDER_OFFSET_2": 14,
    "REMINDER_OFFSET_3": 28,
    "W_RECENT_SYMPTOMS": 5,
    "W_COMORBIDITY": 3,
    "W_FAMILY_HISTORY": 2,
    "CLINIC_THRESHOLD": 6,
}

TEST_DEFAULTS = {
    # Well-known logical-clock values used by the suite.
    "CLOCK_DEFAULT": "2026-09-01T00:00:00Z",
    "DOB_ADULT": "1970-01-01",
    "MEASURE_YEAR": 2026,
}

# Opaque operator user ids (PRD §2.1: not tied to any persisted entity).
USER_IDS = {
    "PROGRAM_ADMIN": "pa-op-1",
    "FULFILLMENT_AGENT": "fa-op-1",
    "LAB_TECHNICIAN": "lt-op-1",
    "NAVIGATOR": "nav-op-1",
}
