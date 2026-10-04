"""Domain thresholds and structural constants.

Every literal below is stated verbatim in PRD.md:
- CLOCK_DEFAULT_UTC:        PRD §2.4  "the logical clock reads exactly
                              `2026-09-01T00:00:00Z`"
- CLOCK_ENDPOINT_PATH:      PRD §4 table row "POST /_clock/set_current_utc";
                            §2.4 states it is mounted OUTSIDE the prefix.
- API_PREFIX:               PRD §1    "All resources are mounted under the
                              `/comm-services` prefix"
- ESCALATION_MIN_AGE_DAYS:  PRD §3.9  "the platform's minimum escalation age
                              of seven days" ("a complaint exactly seven days
                              old may be escalated")
- MESSAGE_BODY_MAX_CHARS:   PRD §3.6  "may not exceed 1000 characters"
- SESSION_MIN_MINUTES:      PRD §3.7  "the session must run at least fifteen
                              minutes"
- DEFAULT_VIDEO_TURNOVER_MINUTES:       PRD §3.1 "defaults to 10"
- DEFAULT_DAILY_SESSION_LIMIT_PER_INMATE: PRD §3.1 "defaults to 2"
- VERIFICATION_CODE_DIGITS: PRD §3.4  "the server generates a six-digit
                              `verification_code`"
- PAGE_*:                   PRD §2.3  "defaults to 10, with a minimum of 1
                              and a maximum of 100"; "defaults to 0"
"""

# --- Logical clock (PRD §2.4) ---
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"
CLOCK_ENDPOINT_PATH = "/_clock/set_current_utc"  # UNPREFIXED (outside prefix)

# --- API mounting (PRD §1) ---
API_PREFIX = "/comm-services"

# --- Time-window thresholds ---
ESCALATION_MIN_AGE_DAYS = 7  # "seven days"
SESSION_MIN_MINUTES = 15  # "at least fifteen minutes"

# --- Field limits ---
MESSAGE_BODY_MAX_CHARS = 1000  # "may not exceed 1000 characters"
VERIFICATION_CODE_DIGITS = 6  # "six-digit verification_code"

# --- Server-side defaults for optional facility fields (PRD §3.1) ---
DEFAULT_VIDEO_TURNOVER_MINUTES = 10  # "defaults to 10"
DEFAULT_DAILY_SESSION_LIMIT_PER_INMATE = 2  # "defaults to 2"

# --- Pagination (PRD §2.3) ---
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

__all__ = [
    "CLOCK_DEFAULT_UTC",
    "CLOCK_ENDPOINT_PATH",
    "API_PREFIX",
    "ESCALATION_MIN_AGE_DAYS",
    "SESSION_MIN_MINUTES",
    "MESSAGE_BODY_MAX_CHARS",
    "VERIFICATION_CODE_DIGITS",
    "DEFAULT_VIDEO_TURNOVER_MINUTES",
    "DEFAULT_DAILY_SESSION_LIMIT_PER_INMATE",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MIN",
    "PAGE_LIMIT_MAX",
    "PAGE_OFFSET_DEFAULT",
]
