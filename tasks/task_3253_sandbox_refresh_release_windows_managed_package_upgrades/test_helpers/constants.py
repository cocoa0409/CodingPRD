"""Domain thresholds and constants from the PRD.

The numeric constants are the ones the PRD states verbatim: the seasonal
ordinals of §2.9, the governor ceiling and per-unit costs of §3.8, the
storage constants of §2.8, the aperture and masking thresholds of §2.9/§3.2
and the layered-access budgets of §2.10.
"""

# Seasonal release train ordering (PRD §2.9).
RELEASE_ORDINALS = {"WI25": 1, "SP26": 2, "SU26": 3, "WI26": 4}
LAUNCH_PROTECT_GENERATIONS = 2

# Refresh-window projection curve (PRD §3.2).
REFRESH_CURVE_STEP_DAYS = 2
REFRESH_CURVE_MODULUS = 3

# Storage (PRD §2.8).
STORAGE_BREACH_COMPARISON = ">="
ARCHIVE_BATCH_FILE_CAP = 3
DEFAULT_STORAGE_CAP_BYTES = 5242880000

# Aperture (PRD §2.9 / §3.2).
REFRESH_APERTURE_BASE_LEVEL = 2
DEFAULT_APERTURE_LIMIT = 2

# Data masking (PRD §3.2).
FULL_COPY_MASKING_MIN = 20

# Governor limits (PRD §3.8).
BATCH_SCOPE_COST_UNITS = 2
CALLOUT_CELL_COST_UNITS = 250
CALLOUT_DEPTH_CELL_LIMIT = 6
ORG_GOVERNOR_CEILING_UNITS = 100000
DEFAULT_MAX_CONCURRENT_JOBS = 5

# Layered access (PRD §2.10).
ADMIN_STANDARD_ACCESS_LAYER_BUDGET = 2
ACCESS_LAYER_BLOCK_DENOMINATOR_ADMIN = 3
ACCESS_LAYER_BLOCK_DENOMINATOR_STANDARD = 2
AUDIT_GRADE_BLOCKED_MIN = 3

# Logical clock (PRD §2.11).  Datetimes are ISO 8601 UTC with three fractional
# digits (PRD §2.11), so the literals carry `.000` to compare equal to the
# server's own serialisation of the same instant.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00.000Z"
SNAPSHOT_DISPATCH_AT = "2026-10-05T00:00:00.000Z"
ASYNC_BACKLOG_LAYERS = 2

# Valid enum members (PRD §2.4 / §3).
ENVIRONMENT_TYPES = ["PRODUCTION", "FULL_COPY", "PARTIAL", "DEVELOPER"]
REFRESH_PARTITIONS = ["FULL", "ACCOUNT_PARTIAL"]
LEDGER_KINDS = ["DATA", "FILE"]
PRINCIPAL_TYPES = ["PROFILE", "PERMISSION_SET"]

# Sensible factory defaults.
TEST_DEFAULTS = {
    "ENVIRONMENT_NAME": "Test Environment",
    "REFRESH_INTERVAL_DAYS": 30,
    "APERTURE_LIMIT": 5,
    "STORAGE_CAP_BYTES": 104857600,
    "SCOPE_COUNT": 5,
    "MAJOR_VERSION": 1,
}