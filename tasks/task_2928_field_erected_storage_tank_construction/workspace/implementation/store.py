"""In-memory data store.

Plain dicts keyed by id, insertion ordered (which is created_at ascending, the
order PRD 2.3 mandates for every list read).  Nothing is seeded: every entity
is built by the caller through the declared endpoints, and a fresh process
starts completely empty.
"""

from datetime import datetime

from util import fmt_dt, new_id, now_real

TANKS = {}
FOUNDATION_PACKAGES = {}
SETTLEMENT_SURVEYS = {}
PLATE_LOTS = {}
SHELL_COURSES = {}
WELDERS = {}
WELD_SEAMS = {}
NDE_REPORTS = {}
WATER_SOURCES = {}
HYDROTEST_PLANS = {}
WATER_WITHDRAWALS = {}
COATING_APPLICATIONS = {}
APPURTENANCES = {}
COMMISSIONING_PACKAGES = {}

ALL_COLLECTIONS = (
    TANKS, FOUNDATION_PACKAGES, SETTLEMENT_SURVEYS, PLATE_LOTS, SHELL_COURSES,
    WELDERS, WELD_SEAMS, NDE_REPORTS, WATER_SOURCES, HYDROTEST_PLANS,
    WATER_WITHDRAWALS, COATING_APPLICATIONS, APPURTENANCES,
    COMMISSIONING_PACKAGES,
)


def new_row(fields):
    """Create a row: id first, the entity fields in order, then the common ones.

    PRD 2.4: every resource carries id, created_at, updated_at and version;
    version starts at 1.
    """
    stamp = now_real()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    return row


def touch(row):
    """A mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = now_real()
    row["version"] = int(row["version"]) + 1
    return row


def touch_time(row):
    """Refresh updated_at only (derived-field refresh on an OCC parent)."""
    row["updated_at"] = now_real()
    return row


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = fmt_dt(value) if isinstance(value, datetime) else value
    return out


def rows(collection):
    return list(collection.values())
