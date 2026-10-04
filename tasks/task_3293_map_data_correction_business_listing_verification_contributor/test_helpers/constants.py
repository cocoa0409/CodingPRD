"""Domain thresholds — numeric constants from PRD calculations."""

# Edit auto-validation score (PRD §3.4)
AUTO_SCORE = {
    "BASE": 40,
    "W_TRUST": 0.4,
    "W_EVIDENCE": 10,
    "EVIDENCE_CAP": 3,
    "RISK_ADDRESS_LOCATION": 25,
    "RISK_NAME_CLEAN": 10,
    "RISK_NAME_STRUCK": 30,
    "RISK_OTHER": 5,
    "AUTO_APPROVE_MIN": 85,
    "QUEUE_MIN": 50,
}

# Contributor points and levels (PRD §3.1)
POINTS = {
    "T_REGULAR": 50,
    "T_TRUSTED": 250,
    "T_EXPERT": 1000,
    "T_MASTER": 5000,
    "EDIT_BASE": 5,
    "REVIEW_BASE": 2,
    "VERIFICATION_ASSIST_BASE": 10,
}

# Level-based edit quality weights (PRD §3.1)
QUALITY_WEIGHT = {
    "NEWCOMER": 0.5,
    "REGULAR": 1.0,
    "TRUSTED": 1.5,
    "EXPERT": 2.0,
    "MASTER": 2.5,
}

# Contributor trust score (PRD §3.6)
TRUST = {
    "BASE": 50,
    "W_PUBLISHED": 3,
    "W_REJECTED": 6,
    "W_REVERTED": 9,
    "PERMANENT_CLOSE_PENALTY": 25,
    "RESTRICT_THRESHOLD": 20,
    "YOUNG_EDIT_DAYS": 7,
}

# Listing health score (PRD §3.6)
HEALTH = {
    "BASE": 50,
    "W_RATING": 4,
    "W_ACCEPTED_EDITS": 2,
    "ACCEPTED_EDITS_CAP": 10,
    "W_REVERT_RATE": 40,
    "W_SUSPENDED": 5,
    "RESTRICT_THRESHOLD": 30,
}

# Hours conflict resolution (PRD §3.7)
HOURS = {
    "RECENCY_WINDOW_DAYS": 30,
    "CORROBORATION_CAP": 5,
    "CORROBORATION_UNIT": 10,
    "PRIORITY_SCALE": 100,
    "PRIORITY_OWNER": 5,
    "PRIORITY_THIRD_PARTY_FEED": 4,
    "PRIORITY_WEB_CRAWL": 3,
    "PRIORITY_IMAGERY": 2,
    "PRIORITY_CONTRIBUTOR": 1,
    "PRIORITY_CONTRIBUTOR_PROMOTED": 3,
}

# Review fake probability (PRD §3.5)
FAKE_REVIEW = {
    "W_LOW_TRUST": 0.10,
    "W_BURST": 0.25,
    "W_SHORT_TEXT": 0.30,
    "W_NEW_ACCOUNT": 0.35,
    "AUTO_FLAG_THRESHOLD": 0.80,
    "BURST_COUNT": 3,
    "SHORT_TEXT_LEN": 20,
    "NEW_ACCOUNT_DAYS": 7,
    "FLAG_LIMIT": 5,
}

# Verification throttles (PRD §3.3)
VERIFICATION = {
    "COOLDOWN_HOURS": 72,
    "MAX_ATTEMPTS_PER_30D": 5,
    "MAX_SUBMIT_ATTEMPTS": 3,
    "EXPIRY_DAYS": 14,
    "REVERIFY_DAYS": 365,
    "FAILED_SUSPENSION_THRESHOLD": 5,
}

# Suspension appeal (PRD §3.6)
APPEAL = {
    "WINDOW_DAYS": 30,
    "MIN_TEXT_LEN": 50,
}

# Region defaults (PRD §2.8)
REGION = {
    "DEFAULT_MAX_ACTIVE_IMAGERY_TASKS": 5,
}

# Logical clock default (PRD §2.4)
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
