"""The logical clock and the system transitions it settles (§2.5, §3.7, §3.13).

Nothing in this API is evaluated against real wall-clock time. Setting the
clock is not a passive operation: it re-evaluates the prerelease and
street-date system transitions of every set release, and it re-evaluates the
reporting deadlines of every non-LOCAL approved event application, marking
already-filed reports OVERDUE once their deadline has passed.
"""

import db as store
import computed as calcs
from utils import clock as logical_clock
from services import cascade


def set_clock(value):
    logical_clock.set(value)
    _settle_set_releases()
    _settle_reporting_deadlines()
    rederive_deadlines()


def _settle_set_releases():
    """ANNOUNCED -> PRERELEASE -> RELEASED as the clock crosses each window.

    A clock advanced past several boundaries or past the whole window in one
    call still settles the release all the way: a release whose prerelease
    window and street date have both been crossed lands on RELEASED, because
    the operator advancing the clock past the street date is exactly the system
    event the cadence describes.
    """
    for release in list(store.db.set_releases.values()):
        now = logical_clock.now()

        if release["status"] == "ANNOUNCED":
            if release["prerelease_start_date"] <= now < release["prerelease_end_date"]:
                # The window merely opens; no other resource is touched.
                store.touch(release, status="PRERELEASE")
            elif now >= release["street_date"]:
                store.touch(release, status="PRERELEASE")

        if release["status"] == "PRERELEASE":
            if now >= release["street_date"]:
                cascade.settle_street_date(release, store.applications_of_set_release(release["id"]))
                store.touch(release, status="RELEASED")
                _grant_format_epoch(release)


def _approved_before_street(release):
    """Approved competitive applications on this release at settlement time."""
    return [
        a for a in store.applications_of_set_release(release["id"])
        if a["status"] == "APPROVED"
    ]


def _grant_format_epoch(release):
    """Every ACTIVE format gains an epoch entry for this set release (§3.7).

    The release moves to legal status in all of them at the epoch the format is
    currently sitting at, which is the epoch the format must not have rotated
    past for the release to remain legal for a sanctioned event.
    """
    for format_row in store.db.formats.values():
        store.db.format_legal_sets.setdefault(format_row["id"], {})
        store.db.format_legal_sets[format_row["id"]][release["id"]] = format_row["current_epoch"]


def _settle_reporting_deadlines():
    """Deadlines lapse quietly: the application's own dimension is left alone.

    Any report already filed against an application whose deadline the clock
    has passed while its prizing_report_status is still NOT_DUE or DUE is
    marked OVERDUE. The mark is applied on the report row so that a late report
    stays visible without the application's reporting dimension being rewritten
    underneath it; because the application's own column keeps reading DUE, an
    operator can still act on the report by normal means.

    Deliberately NOT restricted to applications that sit at COMPLETED: the
    condition §3.6 names is the combination of a lapsed deadline with a prizing
    column that is still NOT_DUE or DUE, and a REPORTED application whose
    column reads DUE is exactly the late-and-still-open case the mark exists to
    surface. Only an application whose column has reached SUBMITTED — meaning
    its reporting obligation was discharged on time — is left unmarked.
    """
    now = logical_clock.now()
    for application in store.db.event_applications.values():
        if application["tier"] == "LOCAL":
            continue
        if application["prizing_report_status"] not in ("NOT_DUE", "DUE"):
            continue
        if application["status"] in ("WITHDRAWN", "DENIED"):
            continue
        deadline = application["reporting_due_by"]
        if deadline is None or deadline >= now:
            continue
        for report in store.reports_for_application(application["id"]):
            if report["status"] == "FILED":
                store.touch(report, status="OVERDUE")


def rederive_deadlines():
    """Re-derive reporting_due_by for every non-LOCAL approved application."""
    for application in store.db.event_applications.values():
        if application["tier"] == "LOCAL":
            continue
        if application["status"] not in ("APPROVED", "COMPLETED", "REPORTED"):
            continue
        release = store.db.set_releases.get(application["set_release_id"])
        if release is None:
            continue
        deadline = calcs.reporting_due_by(application["tier"], release["street_date"])
        if deadline != application["reporting_due_by"]:
            store.touch(application, reporting_due_by=deadline)