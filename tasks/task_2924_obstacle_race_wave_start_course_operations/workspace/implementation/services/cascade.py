"""Multi-link cascades (PRD 2.10 parcel freeze, PRD 3.3 staffing, PRD 3.6 close).

A cascade is never partial and never skips the version bump on a row it changed.
Every row is touched inside exactly one db.mutation() context so no row is
double-bumped within a single operation.
"""

import db
from services import calc

FREEZE_SUSPENDABLE_COURSE_STATUSES = ("DRAFT", "VALIDATED", "PUBLISHED")
FREEZE_HOLDABLE_RELEASE_STATUSES = ("SCHEDULED", "HELD")


def freeze_venue(venue):
    """Links 2-4 of the withdrawal chain plus the FestivalService fan-out.

    Link 2 is deliberately unconditional: a denial or an expiry freezes the
    parcel even when another permit on the same parcel still reads APPROVED.
    """
    if venue["site_posture"] == "OPEN":
        with db.mutation(venue):
            venue["site_posture"] = "FROZEN"

    for course in db.where("courses", venue_id=venue["id"]):
        if course["status"] in FREEZE_SUSPENDABLE_COURSE_STATUSES:
            with db.mutation(course):
                course["status"] = "SUSPENDED"
                course["readiness_posture"] = "FROZEN"
            for wave in calc.waves_of_course(course["id"]):
                if wave["release_status"] in FREEZE_HOLDABLE_RELEASE_STATUSES:
                    with db.mutation(wave):
                        wave["release_status"] = "HELD"
                        wave["hold_reason"] = "VENUE_FROZEN"
        else:
            with db.mutation(course):
                calc.apply_readiness(course)

    for service in db.where("festival_services", venue_id=venue["id"]):
        if service["status"] == "OPEN":
            with db.mutation(service):
                service["status"] = "CLOSED"


def recompute_venue_courses_readiness(venue):
    """Permit approval: readiness_posture refreshes on every course of the parcel."""
    for course in db.where("courses", venue_id=venue["id"]):
        with db.mutation(course):
            calc.apply_readiness(course)


def staffing_change_without_holdback(course):
    """A confirmed shift: headcounts, live rates and readiness refresh."""
    with db.mutation(course):
        calc.apply_course_staffing_fields(course)
        calc.apply_readiness(course)


def staffing_vacate_cascade(course):
    """Links 3-4 of the vacate chain: readiness, then imminent heats to HELD."""
    with db.mutation(course):
        calc.apply_course_staffing_fields(course)
        calc.apply_readiness(course)

    if course["readiness_posture"] != "RESTRICTED":
        return

    horizon = db.plus_minutes(db.now(), calc.HOLDBACK_WINDOW_MINUTES)
    for wave in calc.waves_of_course(course["id"]):
        if wave["release_status"] != "SCHEDULED":
            continue
        if wave["scheduled_start_utc"] <= horizon:
            with db.mutation(wave):
                wave["release_status"] = "HELD"
                wave["hold_reason"] = "COURSE_RESTRICTED"


def close_bubble_up(course):
    """PUBLISHED -> COMPLETED once no heat of the course remains outside CLOSED."""
    waves = calc.waves_of_course(course["id"])
    with db.mutation(course):
        calc.apply_scheduled_capacity(course)
        if (
            course["status"] == "PUBLISHED"
            and waves
            and all(w["release_status"] == "CLOSED" for w in waves)
        ):
            course["status"] = "COMPLETED"
            calc.apply_scheduled_capacity(course)
