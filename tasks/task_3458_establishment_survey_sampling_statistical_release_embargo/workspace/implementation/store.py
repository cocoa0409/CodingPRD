"""In-memory data store, logical clock, constants, and serialization helpers.

Storage is in-memory only (plain dicts keyed by id). A fresh process boots
empty; nothing is seeded at startup. All temporal rules evaluate against the
logical clock, which starts at exactly 2026-09-01T00:00:00Z and never falls
back to wall-clock time.
"""
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# PRD-pinned constants (values verbatim from PRD.md / SCAFFOLD.yaml)
# ---------------------------------------------------------------------------
SIZE_DISPERSION = {"SMALL": 4, "MEDIUM": 15, "LARGE": 50}
MIN_STRATUM_SAMPLE = 2
MIN_CELL_RESPONDENTS = 3
DOMINANCE_THRESHOLD = Decimal("0.60")          # inclusive boundary
MIN_WEIGHTED_RESPONSE_RATE = Decimal("0.600000")
BURDEN_MINUTES_PER_SUBMISSION = 15
DEFAULT_BURDEN_BUDGET_MINUTES = 120
MIN_BURDEN_BUDGET_MINUTES = 15
CONTACT_MIN_MINUTES = 1
CONTACT_MAX_MINUTES = 480
CONTACT_SPACING = timedelta(hours=24)
ESCALATION_MIN_CONTACTS = 2
ESCALATION_MIN_AGE = timedelta(days=7)
COLLECTION_CLOSE_DAY = 20                       # window: 1st 00:00:00Z .. 20th 23:59:59Z
PREANNOUNCE_LEAD = timedelta(days=3)
DEFAULT_EMBARGO_WINDOW_MINUTES = 30
EMBARGO_WINDOW_MIN = 1
EMBARGO_WINDOW_MAX = 1440
FACTOR_COUNT = 12
FACTOR_MIN = Decimal("0.2")
FACTOR_MAX = Decimal("5.0")
FACTOR_MEAN_TOLERANCE = Decimal("0.0005")       # mean within 1.0 +/- tol, inclusive
PPM_BASELINE = 1_000_000
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

INDUSTRIES = ["CONSTRUCTION", "HEALTHCARE", "MANUFACTURING", "RETAIL"]  # ASC
SIZE_CLASSES = ["SMALL", "MEDIUM", "LARGE"]                             # ASC order per PRD

ROLES = [
    "ProgramAdmin", "SurveyMethodologist", "CollectionOfficer", "Respondent",
    "EstimationAnalyst", "DisclosureOfficer", "ReleaseManager", "AccreditedMedia",
]

NONTERMINAL_ENROLLMENT = ("INVITED", "ENROLLED", "SUSPENDED")
LIVE_CASE_STATUSES = ("OPEN", "IN_CONTACT", "ESCALATED")
ACTIVE_GRANT_STATUSES = ("ISSUED", "ACCESSED")

# ---------------------------------------------------------------------------
# Store and clock
# ---------------------------------------------------------------------------
LOCK = threading.RLock()

DB = {
    "programs": {},
    "frames": {},
    "establishments": {},
    "enrollments": {},
    "cycles": {},
    "reports": {},
    "cases": {},
    "cells": {},
    "factor_sets": {},
    "benchmarks": {},
    "notices": {},
    "releases": {},
    "outlets": {},
    "grants": {},
}

_SEQ = {"n": 0}
_CLOCK = {"now": CLOCK_START}


def now() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


def new_id() -> str:
    return str(uuid.uuid4())


def _next_seq() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_entity(kind: str, fields: dict) -> dict:
    ent = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": _next_seq(),
    }
    ent.update(fields)
    DB[kind][ent["id"]] = ent
    return ent


def touch(ent: dict) -> None:
    ent["updated_at"] = now()
    ent["version"] += 1


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt) -> str:
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_instant(value):
    """Parse an ISO 8601 instant to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round6(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round0(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serialization: datetimes -> ISO strings, Decimals -> floats, drop internals
# ---------------------------------------------------------------------------
def serialize(obj):
    if isinstance(obj, datetime):
        return fmt_ts(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [serialize(v) for v in obj]
    return obj


def sorted_entities(kind: str):
    """All entities of a kind, sorted by creation timestamp ascending (PRD 2.3)."""
    return sorted(DB[kind].values(), key=lambda e: (e["created_at"], e["_seq"]))
