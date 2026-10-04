"""Platform constants and small derived-value helpers.

Values here are the literal constants named in the PRD (§2.8 - §2.10, §3.2 -
§3.8).  The heavier derived-field reconciliation rules live in ``services/``;
this module holds only what several of them share.
"""

# --- seasonal release train (PRD §2.9) -------------------------------------
RELEASE_ORDINALS = {"WI25": 1, "SP26": 2, "SU26": 3, "WI26": 4}
LAUNCH_PROTECT_GENERATIONS = 2
STORAGE_ARCHIVE_MIN_RELEASE = 3

# --- refresh window projection (PRD §3.2) ----------------------------------
REFRESH_CURVE_STEP_DAYS = 2
REFRESH_CURVE_MODULUS = 3
REFRESH_APERTURE_BASE_LEVEL = 2

# --- governor limits (PRD §3.8) --------------------------------------------
BATCH_SCOPE_COST_UNITS = 2
CALLOUT_CELL_COST_UNITS = 250
CALLOUT_DEPTH_CELL_LIMIT = 6
ORG_GOVERNOR_CEILING_UNITS = 100000

# --- layered access (PRD §2.10, §3.7) --------------------------------------
ADMIN_STANDARD_ACCESS_LAYER_BUDGET = 2
ACCESS_LAYER_BLOCK_DENOMINATOR_ADMIN = 3
ACCESS_LAYER_BLOCK_DENOMINATOR_STANDARD = 2
AUDIT_GRADE_BLOCKED_MIN = 3

# --- storage (PRD §2.8, §3.6) ----------------------------------------------
STORAGE_BREACH_COMPARISON = ">="
ARCHIVE_BATCH_FILE_CAP = 3

# --- asynchronous backlog projection (PRD §3.8) ----------------------------
ASYNC_BACKLOG_LAYERS = 2
SNAPSHOT_START_KIND = "SNAPSHOT_START"

# --- environment defaults (PRD §2.4) ---------------------------------------
DEFAULT_REFRESH_INTERVAL_DAYS = 30
DEFAULT_STORAGE_CAP_BYTES = 5242880000
DEFAULT_APERTURE_LIMIT = 2
DEFAULT_MAX_CONCURRENT_JOBS = 5
DEFAULT_RELEASE_SCHEDULE_MODE = "MANUAL_FIXED"
RELEASE_SCHEDULE_MODES = ("MANUAL_FIXED", "FLAG_ONLY")
ENVIRONMENT_TYPES = ("PRODUCTION", "FULL_COPY", "PARTIAL", "DEVELOPER")
RELEASE_STATUSES = ("CONFIG", "SCHEDULED", "RELEASED")

# --- ordering helper --------------------------------------------------------
def _ts(row, key):
    return row.get(key) or ""


def sort_asc(rows, key="created_at", seq_key="_seq"):
    """Ascending creation order, with the minting sequence as a stable
    tie-break for rows created within the same clock instant (PRD §2.3)."""
    return sorted(rows, key=lambda r: (_ts(r, key), r.get(seq_key, 0)))


def sort_desc(rows, key="created_at", seq_key="_seq"):
    """Descending creation order — the refresh-history exception (§2.3)."""
    return sorted(rows, key=lambda r: (_ts(r, key), r.get(seq_key, 0)), reverse=True)


def release_ordinal(version):
    if not version:
        return None
    return RELEASE_ORDINALS.get(version)