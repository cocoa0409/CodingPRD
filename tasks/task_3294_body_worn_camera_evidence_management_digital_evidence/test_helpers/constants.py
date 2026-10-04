"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # redaction effort
    "SINGLE_PASS_MIN_PER_MEDIA_MIN": 2,
    "MULTI_PASS_MIN_PER_MEDIA_MIN": 5,
    "LONG_FORM_THRESHOLD_MIN": 120,
    "LONG_FORM_SURCHARGE_MIN": 30,
    # dock charge
    "CHARGE_RATE_PCT_PER_HOUR": 10,
    # device
    "MIN_ASSIGN_BATTERY_PCT": 20,
    # retention (days) by category
    "RETENTION_DAYS": {
        "INCIDENT": 180,
        "ARREST": 1095,
        "TRAFFIC_STOP": 90,
        "TRAINING": 30,
        "TEST": 7,
    },
    "CASE_LINKED_EXTENSION_DAYS": {
        "INCIDENT": 730,
        "ARREST": 2555,
        "TRAFFIC_STOP": 365,
        "TRAINING": 30,
        "TEST": 7,
    },
    # share grants
    "MIN_SHARE_EXPIRY_DAYS": 1,
    "MAX_SHARE_EXPIRY_DAYS": 90,
    # recording shape
    "MAX_DURATION_SECONDS": 14400,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "ONE_GIB": 1073741824,
    "ONE_MIB": 1048576,
}
