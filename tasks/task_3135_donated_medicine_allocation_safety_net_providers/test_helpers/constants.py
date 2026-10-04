"""Domain constants for the Donated Medicine Allocation API.

Numeric thresholds and defaults named by the PRD's calculation narratives.
"""

# ── Need scoring (PRD need-score narrative) ────────────────────────────────
UNDERSERVED_WEIGHT = 100
VOLUME_DIVISOR = 1000
VOLUME_CAP = 2.0
VOLUME_WEIGHT = 25
EMERGENCY_PER_SEVERITY = 10
COLD_CHAIN_SHORTFALL_PENALTY = -50

# ── Reservation TTLs (PRD decision-finalization narrative) ─────────────────
RESERVATION_TTL_HOURS = 72
EMERGENCY_RESERVATION_TTL_HOURS = 24

# ── Logical clock ──────────────────────────────────────────────────────────
CLOCK_EPOCH = "2026-09-01T00:00:00Z"

# ── Pagination defaults (PRD pagination section) ───────────────────────────
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ── Common test defaults ───────────────────────────────────────────────────
DEFAULT_EXPIRATION_DATE = "2027-06-30T00:00:00Z"
DEFAULT_LICENSE_EXPIRY = "2027-12-31T00:00:00Z"
DEFAULT_TEMP_MIN_C = 15.0
DEFAULT_TEMP_MAX_C = 25.0
COLD_TEMP_MIN_C = 2.0
COLD_TEMP_MAX_C = 8.0
DEFAULT_ACQUISITION_VALUE = 1.00
DEFAULT_WHOLESALE_VALUE = 1.50

NON_EXISTENT_ID = "00000000-0000-0000-0000-000000000000"
