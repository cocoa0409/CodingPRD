"""Domain thresholds and constants from the PRD (§2.4, §2.7, §3)."""

# Logical clock (PRD §2.4): server startup reads this instant; never wall-clock.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# Fragment category multipliers (PRD §2.7).
CATEGORY_MULTIPLIERS = {
    "DIRECT_QUOTE": 1.0,
    "PARAPHRASE": 0.8,
    "BIBLIOGRAPHY_ENTRY": 1.0,
    "BOILERPLATE": 0.5,
}

# AI confidence blend weights (PRD §2.7).
AI_WEIGHTS = {
    "ai_burstiness": 0.5,
    "ai_perplexity": 0.3,
    "ai_stylometry": 0.2,
}

# Confidence-band spread boundaries (PRD §3.6).
BAND_HIGH_MAX_SPREAD = 0.15
BAND_MEDIUM_MAX_SPREAD = 0.30

# Conservative-bound margins in basis points (PRD §3.6).
BAND_MARGINS_BPS = {
    "HIGH": 500,
    "MEDIUM": 1500,
    "LOW": 2500,
}

# AI assessment minimum word count (PRD §3.6).
AI_MIN_WORD_COUNT = 250

# small_match_threshold_words allowed range (PRD §3.3).
SMALL_MATCH_THRESHOLD_MIN = 1
SMALL_MATCH_THRESHOLD_MAX = 32
SMALL_MATCH_THRESHOLD_DEFAULT = 8

# max_submissions_per_student defaults/range (PRD §3.3).
MAX_SUBMISSIONS_DEFAULT = 3
MAX_SUBMISSIONS_MIN = 1
MAX_SUBMISSIONS_MAX = 10

# Purge grace window length in days (PRD §3.9).
PURGE_GRACE_DAYS = 7

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
