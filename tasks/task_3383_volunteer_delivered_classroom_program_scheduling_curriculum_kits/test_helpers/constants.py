"""Domain thresholds and derived-value helpers (PRD §2.4, §2.10, §3.3-§3.7).

Every literal here is stated in PRD prose:
- kit requirement: 3 base kits plus session_count * ceil(enrolled * 0.20) (§3.4)
- funding floor: 75,000 + 25,000 * session_count cents (§3.3)
- recognition ladder: GOLD 40h/2,000,000c; SILVER 25h+1,000,000c or 60h alone;
  BRONZE 10h+500,000c or funding-only 2,000,000c (§3.3)
- cadence band: [3, 14] days inclusive (§3.5)
- facility capacities: SIMULATED_TOWN 60, FINANCE_PARK 90, buffer 30 minutes (§3.7)
- credential lifetime: 365 days (§3.2); delivery window: 7 days (§3.5)
- logical clock default: 2026-09-01T00:00:00Z (§2.4)
"""
import math

# Logical clock
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
CREDENTIAL_TTL_DAYS = 365
DELIVERY_WINDOW_DAYS = 7

# Kit requirement (PRD §3.4)
BASE_KITS = 3
SESSION_PACK_RATIO = 0.20

# Funding floor (PRD §3.3)
FUNDING_BASE_CENTS = 75000
FUNDING_PER_SESSION_CENTS = 25000

# Recognition tier ladder (PRD §3.3)
GOLD_HOURS = 40
GOLD_FUNDING_CENTS = 2000000
SILVER_HOURS = 25
SILVER_FUNDING_CENTS = 1000000
SILVER_HOURS_ONLY = 60
BRONZE_HOURS = 10
BRONZE_FUNDING_CENTS = 500000

# Session cadence (PRD §3.5)
MIN_SESSION_GAP_DAYS = 3
MAX_SESSION_GAP_DAYS = 14

# Facility capacity (PRD §3.7)
TOWN_CAPACITY = 60
PARK_CAPACITY = 90
TURNOVER_BUFFER_MINUTES = 30

# School instructional weekdays used across fixtures (PRD §3.1)
ALL_WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI"]

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0


def funding_floor_cents(session_count: int) -> int:
    """floor = 75,000 + 25,000 * session_count (PRD §3.3)."""
    return FUNDING_BASE_CENTS + session_count * FUNDING_PER_SESSION_CENTS


def required_kits(enrolled_count: int, session_count: int) -> int:
    """3 base + session_count * ceil(enrolled * 0.20); ceil per session first (PRD §3.4)."""
    per_session_packs = math.ceil(enrolled_count * SESSION_PACK_RATIO)
    return BASE_KITS + session_count * per_session_packs
