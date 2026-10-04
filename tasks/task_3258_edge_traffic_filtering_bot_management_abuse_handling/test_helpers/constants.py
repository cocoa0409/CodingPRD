"""Domain thresholds and numeric constants from the PRD."""

# Fixed startup value of the logical clock before any operator intervention.
CLOCK_START = "2026-09-01T00:00:00Z"

# Support first-response SLA in hours, derived from plan tier at account creation.
SUPPORT_SLA_HOURS = {
    "FREE": 72,
    "PRO": 24,
    "BUSINESS": 8,
    "ENTERPRISE": 4,
}

# Plan feature matrix: which gated features each tier unlocks.
PLAN_FEATURES = {
    "FREE": {
        "rate_limiting": False,
        "bot_classification": False,
        "managed_rulesets": False,
        "dos_sensitivity": False,
        "origin_shield": False,
        "cache_reserve": False,
    },
    "PRO": {
        "rate_limiting": True,
        "bot_classification": True,
        "managed_rulesets": True,
        "dos_sensitivity": True,
        "origin_shield": True,
        "cache_reserve": False,
    },
    "BUSINESS": {
        "rate_limiting": True,
        "bot_classification": True,
        "managed_rulesets": True,
        "dos_sensitivity": True,
        "origin_shield": True,
        "cache_reserve": True,
    },
    "ENTERPRISE": {
        "rate_limiting": True,
        "bot_classification": True,
        "managed_rulesets": True,
        "dos_sensitivity": True,
        "origin_shield": True,
        "cache_reserve": True,
    },
}

# DoS mitigation trigger constants.
AUTO_THRESHOLD_MULTIPLIER = 20
SENSITIVITY_MULTIPLIER = {
    "HIGH": 0.5,
    "DEFAULT": 1.0,
    "LOW": 2.0,
}
AUTO_MITIGATION_TTL_HOURS = 4

# Bot classification constants.
HONEYPOT_LOOKBACK_SECONDS = 86400
HUMAN_SCORE = 30
VERIFIED_SCORE = 99
FIGHT_MODE_MIN_SCORE = 1
FIGHT_MODE_MAX_SCORE = 29

# Rate limiting window.
RATE_LIMIT_WINDOW_SECONDS = 60

# Purge completion latency, whole seconds on the logical clock.
SHIELD_PER_ENTRY_COMPLETION_SECONDS = 900
UNSHIELDED_PER_ENTRY_COMPLETION_SECONDS = 0

# IP block durations, whole seconds.
BLOCK_BASE_SECONDS = 3600
PROVISIONAL_WINDOW_SECONDS = 900
RELEASE_GRACE_FRACTION = 0.025

# Abuse priority category base weights.
CATEGORY_BASE = {
    "CSAM": 1000,
    "PHISHING": 800,
    "MALWARE": 700,
    "COPYRIGHT": 500,
    "SPAM": 300,
    "OTHER": 100,
}

TEST_DEFAULTS = {
    "COMPANY_NAME": "Test Corp",
    "ACCOUNT_EMAIL": "ops@test.example.com",
    "ORIGIN_HOST_EMAIL": "host@provider.example.com",
    "POP_CAPACITY_GBPS": 200,
    "EDGE_TTL_SECONDS": 3600,
}
