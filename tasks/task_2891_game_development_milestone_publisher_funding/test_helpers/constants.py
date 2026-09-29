"""Business constants taken verbatim from the PRD.

Every literal in this module is a figure the PRD states explicitly: role names,
gate-profile thresholds, holdback tiers, basis-point caps and the logical clock's
documented starting instant.
"""

# --- Roles (PRD §2.1: the comparison against X-User-Role is case-sensitive) ---
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_DEVELOPER = "Developer"
ROLE_PUBLISHER_REVIEWER = "PublisherReviewer"
ROLE_PUBLISHER_FINANCE = "PublisherFinance"

# --- PublisherUser.function values (PRD §2.1 / §3.1) ---
FUNCTION_REVIEW = "REVIEW"
FUNCTION_FINANCE = "FINANCE"
FUNCTION_DUAL = "DUAL"

# --- Logical clock (PRD §2.4) ---
CLOCK_START = "2026-08-01T00:00:00.000Z"

# --- Gate profiles (PRD §3.4) ---
GATE_PROFILES = {
    "ALPHA": {"feature": 70.00, "crash_free": 95.00, "content": 50.00, "blockers": 20},
    "BETA": {"feature": 90.00, "crash_free": 98.00, "content": 80.00, "blockers": 5},
    "GOLD": {"feature": 100.00, "crash_free": 99.50, "content": 100.00, "blockers": 0},
}

# Readiness weights (PRD §3.4)
READINESS_WEIGHT_FEATURE = 0.45
READINESS_WEIGHT_CRASH_FREE = 0.35
READINESS_WEIGHT_CONTENT = 0.20

# Gate adjustments (PRD §3.4)
CURE_CONTENT_UPLIFT_PCT = 5.00
STABILITY_SURPLUS_PCT = 0.50
FEATURE_RELAXATION_PCT = 2.00

# --- Holdback ladder (PRD §3.6) ---
HOLDBACK_TIER_1_CEILING_CENTS = 2500000
HOLDBACK_TIER_2_CEILING_CENTS = 10000000
HOLDBACK_TIER_1_BPS = 0
HOLDBACK_TIER_2_BPS = 500
HOLDBACK_TIER_3_BPS = 1000
CURE_PENALTY_BPS_PER_ROUND = 250
CURE_PENALTY_BPS_CAP = 500

# --- Caps and thresholds expressed in basis points (PRD §2.6, §3.7, §3.8) ---
RESTRICTED_POSTURE_BPS = 3000
UPLIFT_CAP_BPS = 2500
INVOICE_TOLERANCE_BPS = 12500
MAX_SLIP_DAYS = 45
VENDOR_COOLDOWN_DAYS = 3

# --- Cure windows (PRD §3.5) ---
DEFAULT_CURE_DAYS = 14
MAX_CURE_ROUNDS = 2

# --- Live-ops (PRD §3.9) ---
LIVE_OPS_QUARTERS = 4

# --- IP reversion thresholds (PRD §3.9) ---
IP_PARTIAL_REVERSION_RATIO = 0.5000
IP_RETAINED_RATIO = 0.8000

# --- Rate defaults (PRD §3.1) ---
DEFAULT_RECOUPABLE_COST_CAP_BPS = 2000
DEFAULT_PLATFORM_FEE_BPS = 3000
DEFAULT_LIVE_OPS_QUARTERLY_FUNDING_CENTS = 0

# --- Identifiers that resolve to nothing ---
UNKNOWN_AGREEMENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_MILESTONE_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_ENGAGEMENT_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_ACTOR_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_IDS = {
    "studio": "00000000-0000-4000-8000-000000000001",
    "publisher": "00000000-0000-4000-8000-000000000002",
    "publisher_user": "00000000-0000-4000-8000-000000000003",
    "agreement": "00000000-0000-4000-8000-000000000004",
    "milestone": "00000000-0000-4000-8000-000000000005",
    "build": "00000000-0000-4000-8000-000000000006",
    "review": "00000000-0000-4000-8000-000000000007",
    "payment": "00000000-0000-4000-8000-000000000008",
    "change_order": "00000000-0000-4000-8000-000000000009",
    "engagement": "00000000-0000-4000-8000-00000000000a",
    "invoice": "00000000-0000-4000-8000-00000000000b",
    "statement": "00000000-0000-4000-8000-00000000000c",
}

# --- Recurring gate-clearing build metrics (all derived from PRD §3.4 bars) ---
ALPHA_PASSING_METRICS = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}
BETA_PASSING_METRICS = {
    "feature_completeness_pct": 95.00,
    "crash_free_sessions_pct": 98.50,
    "content_completeness_pct": 85.00,
    "known_blocker_count": 2,
}
GOLD_PASSING_METRICS = {
    "feature_completeness_pct": 100.00,
    "crash_free_sessions_pct": 99.50,
    "content_completeness_pct": 100.00,
    "known_blocker_count": 0,
}
