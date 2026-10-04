"""Domain thresholds and constants from the program's calculations (PRD §3)."""

# ─── Tier prize support (PRD §3.5) ────────────────────
TIER_BASE_TP = {"LOCAL": 16, "QUALIFIER": 48, "CHAMPIONSHIP": 96}
POD_BUNDLE_MINIMUM = 4
POD_BUNDLE_TP = {"LOCAL": 3, "QUALIFIER": 6, "CHAMPIONSHIP": 12}
POD_TP_PER_MEMBER = 4

# ─── Physical grant value (PRD §3.11) ─────────────────
PACK_COUNT_BY_TIER = {"LOCAL": 6, "QUALIFIER": 12, "CHAMPIONSHIP": 24}
PACK_VALUE_NUM = 27
PACK_VALUE_DEN = 4

# ─── Reporting deadlines (PRD §3.2, §3.4) ─────────────
REPORTING_WINDOW_DAYS = 18
EVENT_COMPLETION_DAYS_AFTER_STREET = 7

# ─── Headcount gate (PRD §3.13) ───────────────────────
QUALIFIED_THRESHOLD = 24

# ─── Reprint policy (PRD §3.9) ────────────────────────
WOW_ADDENDUM_NUMERATOR = 64
WOW_ADDENDUM_DENOMINATOR = 137
REPRINT_CEILING_INDEX = 42

# ─── Reporting discipline (PRD §3.1) ──────────────────
ENHANCED_REPORTING_THRESHOLD = 5

# ─── Enforcement scoring (PRD §3.10) ──────────────────
CLASS_POINTS = {"MINOR": 2, "MAJOR": 5, "SEVERE": 11}
LEVEL_MULTIPLIER = {"REGULAR": 1, "COMPETITIVE": 2, "PROFESSIONAL": 3}
REPEAT_MULTIPLIER = 3
ESCALATION_INCREMENT = 4

# ─── Calendar locks (PRD §2.5) ────────────────────────
CLOCK_START = "2026-09-01T00:00:00Z"
ROTATION_LOCK_DATE = "2026-10-15T00:00:00Z"
REPRINT_PUBLICATION_CUTOFF = "2026-12-01T00:00:00Z"

# The canonical set release used across fixtures.
SET_STREET_DATE = "2026-09-18T00:00:00Z"
SET_PRERELEASE_START = "2026-09-11T00:00:00Z"
SET_PRERELEASE_END = "2026-09-13T23:59:59Z"

# A clock reading strictly inside the prerelease weekend.
PRERELEASE_MIDPOINT = "2026-09-12T12:00:00Z"

THRESHOLDS = {
    "TIER_BASE_TP": TIER_BASE_TP,
    "POD_BUNDLE_MINIMUM": POD_BUNDLE_MINIMUM,
    "POD_BUNDLE_TP": POD_BUNDLE_TP,
    "POD_TP_PER_MEMBER": POD_TP_PER_MEMBER,
    "PACK_COUNT_BY_TIER": PACK_COUNT_BY_TIER,
    "PACK_VALUE_NUM": PACK_VALUE_NUM,
    "PACK_VALUE_DEN": PACK_VALUE_DEN,
    "REPORTING_WINDOW_DAYS": REPORTING_WINDOW_DAYS,
    "EVENT_COMPLETION_DAYS_AFTER_STREET": EVENT_COMPLETION_DAYS_AFTER_STREET,
    "QUALIFIED_THRESHOLD": QUALIFIED_THRESHOLD,
    "REPRINT_CEILING_INDEX": REPRINT_CEILING_INDEX,
    "ENHANCED_REPORTING_THRESHOLD": ENHANCED_REPORTING_THRESHOLD,
    "CLASS_POINTS": CLASS_POINTS,
    "LEVEL_MULTIPLIER": LEVEL_MULTIPLIER,
    "REPEAT_MULTIPLIER": REPEAT_MULTIPLIER,
    "ESCALATION_INCREMENT": ESCALATION_INCREMENT,
}

TEST_DEFAULTS = {
    "DAILY_EVENT_CAPACITY": 8,
    "EVENT_SPACE_CAPACITY": 8,
    "EXPECTED_HEADCOUNT": 30,
}


def physical_grant_value(tier: str) -> int:
    """floor(pack_count * 27 / 4) for the pool's tier, floored once (PRD §3.11)."""
    return (PACK_COUNT_BY_TIER[tier] * PACK_VALUE_NUM) // PACK_VALUE_DEN


def bundled_pool(tier: str, member_count: int) -> int:
    """BUNDLED pool size for `member_count` redeemed digital members (PRD §3.5)."""
    base = TIER_BASE_TP[tier]
    if member_count >= POD_BUNDLE_MINIMUM:
        return base + POD_BUNDLE_TP[tier] * (member_count - POD_BUNDLE_MINIMUM)
    return base


def unbundled_pool(tier: str, member_count: int) -> int:
    """UNBUNDLED pool size for `member_count` redeemed digital members (PRD §3.5)."""
    return TIER_BASE_TP[tier] + POD_TP_PER_MEMBER * member_count


def wow_index(secondary_market_index: int) -> int:
    """Addendum-adjusted index: index + floor(64 * index / 137) (PRD §3.9)."""
    return secondary_market_index + (
        WOW_ADDENDUM_NUMERATOR * secondary_market_index // WOW_ADDENDUM_DENOMINATOR
    )


def tier_penalty(offense_class: str, rules_enforcement_level: str) -> int:
    """penalty_points = class_points * level_multiplier (PRD §3.10)."""
    return CLASS_POINTS[offense_class] * LEVEL_MULTIPLIER[rules_enforcement_level]