"""Path resolution and VenueOperator ownership narrowing (PRD 2.1, 2.8, 2.12).

Ladder rule 2 (authorisation) sits above rule 3 (path existence), so a row that
exists but belongs to another venue yields 403 while a row that does not exist
at all yields the matching 404 -- ownership simply cannot be evaluated against a
row that is not there.
"""

from flask import g

import db
from core import ROLE_OPERATOR, forbidden, not_found

ERR_SOCIETY = "ERR_SOCIETY_NOT_FOUND"
ERR_SCHEDULE = "ERR_RATE_SCHEDULE_NOT_FOUND"
ERR_VENUE = "ERR_VENUE_NOT_FOUND"
ERR_APPLICATION = "ERR_APPLICATION_NOT_FOUND"
ERR_LICENSE = "ERR_LICENSE_NOT_FOUND"
ERR_WINDOW = "ERR_COVERAGE_WINDOW_NOT_FOUND"
ERR_WORK = "ERR_WORK_NOT_FOUND"
ERR_REPORT = "ERR_REPORT_NOT_FOUND"
ERR_ENTRY = "ERR_SETLIST_ENTRY_NOT_FOUND"
ERR_CASE = "ERR_AUDIT_CASE_NOT_FOUND"
ERR_ASSESSMENT = "ERR_ASSESSMENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Which Venue a row resolves to
# ---------------------------------------------------------------------------


def venue_of_license(license_row):
    return license_row["venue_id"]


def venue_of_window(window):
    license_row = db.license_row(window["license_id"])
    return license_row["venue_id"] if license_row else None


def venue_of_report(report):
    license_row = db.license_row(report["license_id"])
    return license_row["venue_id"] if license_row else None


def venue_of_entry(entry):
    report = db.report(entry["performance_report_id"])
    return venue_of_report(report) if report else None


def venue_of_row(table, row):
    if table == "venues":
        return row["id"]
    if table in ("applications", "licenses", "audit_cases", "assessments"):
        return row["venue_id"]
    if table == "coverage_windows":
        return venue_of_window(row)
    if table == "reports":
        return venue_of_report(row)
    if table == "entries":
        return venue_of_entry(row)
    return None


def is_operator():
    return getattr(g, "user_role", None) == ROLE_OPERATOR


def owns(venue_id):
    return venue_id is not None and venue_id == g.user_id


def fetch(table, row_id, error_id, narrow=True):
    """Resolve one path identifier under the ladder's rule-2-before-rule-3 order."""
    row = db.get(table, row_id)
    if row is not None and narrow and is_operator():
        if not owns(venue_of_row(table, row)):
            raise forbidden("This row does not belong to the acting venue.")
    if row is None:
        raise not_found(error_id)
    return row


# ---------------------------------------------------------------------------
# List narrowing (PRD 4: filters combine on top of the role narrowing)
# ---------------------------------------------------------------------------


def narrow_rows(table, rows):
    if not is_operator():
        return rows
    return [row for row in rows if owns(venue_of_row(table, row))]
