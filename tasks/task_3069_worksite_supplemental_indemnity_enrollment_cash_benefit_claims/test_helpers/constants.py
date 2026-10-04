"""Domain constants: roles, the default logical-clock instant, and money in cents.

The PRD's logical clock reads exactly 2026-09-01T00:00:00Z before any client sets it,
and every scenario pins that as its zero instant.
"""

# --- Roles (PRD section 2.1) ---
ROLE_CARRIER_ADMIN = "CarrierAdmin"
ROLE_GROUP_ADMIN = "GroupAdmin"
ROLE_BENEFIT_COUNSELOR = "BenefitCounselor"
ROLE_CLAIMS_ADJUSTER = "ClaimsAdjuster"
ROLE_POLICYHOLDER_SERVICES = "PolicyholderServices"

ALL_ROLES = (
    ROLE_CARRIER_ADMIN,
    ROLE_GROUP_ADMIN,
    ROLE_BENEFIT_COUNSELOR,
    ROLE_CLAIMS_ADJUSTER,
    ROLE_POLICYHOLDER_SERVICES,
)

# --- Logical clock ---
CLOCK_START = "2026-09-01T00:00:00Z"

# --- Default scenario geometry ---
DEFAULT_WINDOW_START = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-10-01T00:00:00Z"
DEFAULT_PERIOD_START = "2026-09-01T00:00:00Z"
DEFAULT_PERIOD_END = "2026-10-01T00:00:00Z"
DEFAULT_EFFECTIVE_DATE = "2026-01-01T00:00:00Z"
DEFAULT_HIRE_DATE = "2026-01-01T00:00:00Z"

__all__ = [
    "ROLE_CARRIER_ADMIN",
    "ROLE_GROUP_ADMIN",
    "ROLE_BENEFIT_COUNSELOR",
    "ROLE_CLAIMS_ADJUSTER",
    "ROLE_POLICYHOLDER_SERVICES",
    "ALL_ROLES",
    "CLOCK_START",
    "DEFAULT_WINDOW_START",
    "DEFAULT_WINDOW_END",
    "DEFAULT_PERIOD_START",
    "DEFAULT_PERIOD_END",
    "DEFAULT_EFFECTIVE_DATE",
    "DEFAULT_HIRE_DATE",
]
