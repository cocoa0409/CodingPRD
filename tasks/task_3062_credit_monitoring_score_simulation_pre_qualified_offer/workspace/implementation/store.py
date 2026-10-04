"""In-memory data store. Nothing is ever seeded: every map starts empty."""

import uuid as _uuid
from datetime import datetime, timedelta, timezone

EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Global governance constants (scaffold calculations.governance_thresholds).
SCORE_ALERT_DEFAULT_THRESHOLD = 20
PULL_COOLDOWN_HOURS = 24
SNAPSHOT_STALENESS_DAYS = 30
PREQUAL_CACHE_DAYS = 30
CONSENT_SEAL_MAX_PER_RUN = 25
RETENTION_DAYS = 365
PENDING_DISPUTE_CAP = 3
CONTENT_QUALITY_MIN = 8000
OFFER_CAP_BPS = 5000

# Order of the daily operations run's constituent stages.
OPS_STAGES = [
    "daily_mobility",
    "settlement",
    "adverse_selection",
    "consent_sealing",
    "retention",
    "cap_window",
    "stale_offer",
    "calibration",
    "posture_rollup",
]

# ---------------------------------------------------------------------------
# Entity tables. Every one of these begins empty on every process boot.
# ---------------------------------------------------------------------------
consumers = {}
bureau_snapshots = {}
score_factor_explanations = {}
score_alerts = {}
score_alert_thresholds = {}
score_simulations = {}
product_catalog_items = {}
lenders = {}
lender_programs = {}
targeting_criteria = {}
pre_qual_decisions = {}
consent_records = {}
referrals = {}
dispute_referrals = {}
revenue_entries = {}
score_tiers = {}
pre_qualified_offers = {}
render_policies = {}
content_quality_facets = {}
offer_presentation_caps = {}
ops_runs = {}

# ---------------------------------------------------------------------------
# Logical clock. Defaults to EPOCH and is never derived from wall time.
# ---------------------------------------------------------------------------
_clock = {"now": EPOCH}

# Scoring-model factor table: factor_code -> (direction, impact_points).
# Populated through the score-tier endpoints; never preloaded.
FACTOR_TABLE = {}


def now():
    return _clock["now"]


def set_clock(moment):
    _clock["now"] = moment


def clock_start():
    return EPOCH


_UUID_NS = _uuid.UUID("6f5a2e6e-3c58-4d6f-9a5b-2f2c9db4a001")


def new_id():
    return str(_uuid.uuid5(_UUID_NS, _uuid.uuid4().hex))


def heredoc_placeholder():  # pragma: no cover - kept for clarity
    return None


def make_row(fields, moment=None):
    """Build a fresh common-field row carrying `fields` plus the common props."""
    moment = moment or now()
    row = {
        "id": new_id(),
        "created_at": moment,
        "updated_at": moment,
        "version": 1,
    }
    row.update(fields)
    return row