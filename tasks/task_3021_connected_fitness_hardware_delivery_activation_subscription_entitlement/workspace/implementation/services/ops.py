"""The operations sweep and the logical clock panel."""

import clock
import db
from services import calc, classes, membership as membership_service


def advance_published_sessions_to_streaming():
    """PUBLISHED → STREAMING at starts_at for a LIVE session (automatic).

    PRD section 3.8: once the clock has reached the session start, is still
    before the end and has not passed the license end, the session moves to
    STREAMING without any request from the instructor.
    """
    advanced = 0
    current = clock.now()
    for session in db.STORE["class_sessions"].values():
        if session["scheduled_status"] != "PUBLISHED":
            continue
        if session["delivery_mode"] != "LIVE":
            continue
        if (
            current >= session["starts_at"]
            and current < session["ends_at"]
            and current <= session["license_ends_at"]
        ):
            session["scheduled_status"] = "STREAMING"
            db.touch(session)
            advanced += 1
    return advanced


def _archive_elapsed_sessions(current):
    archived_sessions = 0
    expired_enrollments = 0

    for session in list(db.STORE["class_sessions"].values()):
        status = session["scheduled_status"]
        if status == "PUBLISHED":
            # Archived once the clock reaches the end for either delivery mode,
            # or once the licensing window has become void because the session
            # was published after the licence had already ended.
            licensing_voided = (
                current >= session["license_starts_at"]
                and session["created_at"] >= session["license_ends_at"]
            )
            if current >= session["ends_at"] or licensing_voided:
                mode = "PUBLISHED"
            else:
                continue
        elif status == "STREAMING":
            if current < session["ends_at"]:
                continue
            mode = "STREAMING"
        else:
            continue

        if mode == "PUBLISHED":
            # The PUBLISHED archive cascades ENROLLED and WAITLISTED to EXPIRED.
            before = sum(
                1
                for enrollment in db.STORE["class_enrollments"].values()
                if enrollment["class_session_id"] == session["id"]
                and enrollment["status"] in classes.OPEN_ENROLLMENT_STATES
            )
        else:
            # The STREAMING archive only drops untouched seats; nothing expires.
            before = 0
        classes.archive(session, mode)
        expired_enrollments += before
        archived_sessions += 1

    return archived_sessions, expired_enrollments


def _settle_reactivated_memberships():
    """REACTIVATED → ACTIVE: the waypoint settles on the next system step.

    PRD section 3.4 describes REACTIVATED as transient rather than a resting
    state, so the sweep carries every reactivated household into the normal
    live lifecycle.
    """
    settled = 0
    for membership in db.STORE["memberships"].values():
        if membership["status"] != "REACTIVATED":
            continue
        membership_service.settle_reactivated(membership)
        settled += 1
    return settled


def _promote_waitlists():
    promoted = 0
    for session in db.STORE["class_sessions"].values():
        if session["scheduled_status"] in classes.SESSION_TERMINAL:
            continue
        promoted += classes.promote_waitlisted(session)
    return promoted


def _terminate_stale_memberships(current):
    terminated = 0
    decommissioned = 0

    for membership in list(db.STORE["memberships"].values()):
        if membership["status"] != "CANCELLED":
            continue
        stale_days = (current - membership["billing_cycle_start_at"]).days
        if stale_days <= calc.TERMINATION_GRACE_DAYS:
            continue
        decommissioned += sum(
            1
            for device in db.STORE["devices"].values()
            if device["membership_id"] == membership["id"]
            and device["activation_status"] != "DECOMMISSIONED"
        )
        membership_service.terminate(membership)
        terminated += 1

    return terminated, decommissioned


def _refresh_affected_postures():
    affected = set()
    for enrollment in db.STORE["class_enrollments"].values():
        device = db.STORE["devices"].get(enrollment["device_id"])
        if device is not None and device["membership_id"] is not None:
            affected.add(device["membership_id"])
    for membership_id in affected:
        membership = db.STORE["memberships"].get(membership_id)
        if membership is not None:
            calc.recompute_membership(membership, bump=False)


def run_sweep():
    """run_ops_sweep: the batched form of four time-dependent rules.

    The sweep advances every rule a clock step makes reachable at once: live
    sessions start streaming, elapsed sessions archive and expire their open
    enrollments, waitlists promote, stale cancelled memberships terminate, and
    reactivated households settle into ACTIVE.  It returns a summary of what it
    touched, reporting archived sessions, expired enrollments, promoted
    waitlisters, terminated memberships and decommissioned devices.
    """
    advance_published_sessions_to_streaming()
    _settle_reactivated_memberships()
    current = clock.now()

    archived_sessions, expired_enrollments = _archive_elapsed_sessions(current)
    promoted_waitlisters = _promote_waitlists()
    terminated_memberships, decommissioned_devices = _terminate_stale_memberships(current)
    _refresh_affected_postures()

    return {
        "archived_sessions": archived_sessions,
        "expired_enrollments": expired_enrollments,
        "promoted_waitlisters": promoted_waitlisters,
        "terminated_memberships": terminated_memberships,
        "decommissioned_devices": decommissioned_devices,
    }


def set_current_utc(payload):
    from errors import api_error
    from services.common import field_datetime, reject_unknown

    reject_unknown(payload, {"current_utc"})
    if "current_utc" not in payload or payload["current_utc"] is None:
        raise api_error("ERR_INVALID_REQUEST", "Field 'current_utc' is required.")
    instant = field_datetime(payload, "current_utc")
    clock.set_now(instant)
    return {"current_utc": clock.fmt(instant)}