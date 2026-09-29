"""In-memory store.

Plain Python dicts, nothing persisted, nothing seeded.  The store is created
empty at import time and every row in it is written by a client call through a
declared endpoint (PRD 4).  A fresh process therefore starts with no state at
all, which is what `--isolation per-test-server` requires.
"""

import threading

from core import DEFAULT_CLOCK, new_id

LOCK = threading.RLock()

# One dict per entity, keyed by id.  Insertion order is preserved by CPython
# dicts, and each row also carries a monotonic `_seq` used as the tie-break for
# the `created_at ASC` default ordering of PRD 2.3.
TABLES = (
    "societies",
    "rate_schedules",
    "venues",
    "applications",
    "licenses",
    "coverage_windows",
    "works",
    "reports",
    "entries",
    "audit_cases",
    "assessments",
)

STORE = {}

# The logical licensing clock of PRD 2.4.  Nothing in this system reads the
# wall clock for a business decision.
CLOCK = {"now": DEFAULT_CLOCK}

_SEQ = {"n": 0}


def reset():
    for table in TABLES:
        STORE[table] = {}
    CLOCK["now"] = DEFAULT_CLOCK
    _SEQ["n"] = 0


reset()


def now():
    return CLOCK["now"]


def set_now(instant):
    CLOCK["now"] = instant


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def insert(table, row):
    """Insert a row that already carries id/created_at."""
    row["_seq"] = next_seq()
    STORE[table][row["id"]] = row
    return row


def new_row(table, fields, versioned=True):
    """Create a row with the PRD 2.5 audit triplet and insert it."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = now()
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    return insert(table, row)


def new_thin_row(table, fields):
    """PRD 2.5: RepertoireWork and SetlistEntry carry only id and created_at."""
    return new_row(table, fields, versioned=False)


def touch(row):
    """PRD 2.5: every mutation refreshes updated_at and bumps version by 1."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return STORE[table].get(row_id)


def ordered(table):
    """All rows of a table in the PRD 2.3 default order: created_at ascending."""
    return sorted(STORE[table].values(), key=lambda row: (row["created_at"], row["_seq"]))


def where(table, **filters):
    rows = []
    for row in ordered(table):
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Convenience accessors used across the service layer
# ---------------------------------------------------------------------------


def society(society_id):
    return get("societies", society_id)


def schedule(schedule_id):
    return get("rate_schedules", schedule_id)


def venue(venue_id):
    return get("venues", venue_id)


def application(application_id):
    return get("applications", application_id)


def license_row(license_id):
    return get("licenses", license_id)


def window(window_id):
    return get("coverage_windows", window_id)


def work(work_id):
    return get("works", work_id)


def report(report_id):
    return get("reports", report_id)


def entry(entry_id):
    return get("entries", entry_id)


def audit_case(case_id):
    return get("audit_cases", case_id)


def assessment(assessment_id):
    return get("assessments", assessment_id)


def licenses_of_venue(venue_id):
    return where("licenses", venue_id=venue_id)


def assessments_of_venue(venue_id):
    return where("assessments", venue_id=venue_id)


def windows_of_license(license_id):
    return where("coverage_windows", license_id=license_id)


def reports_of_license(license_id):
    return where("reports", license_id=license_id)


def entries_of_report(report_id):
    return where("entries", performance_report_id=report_id)


def cases_of_venue(venue_id):
    return where("audit_cases", venue_id=venue_id)
