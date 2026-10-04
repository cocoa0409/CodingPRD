"""ClassSession, ClassEnrollment, capacity, waitlists and leaderboard integrity."""

import clock
import db
from errors import api_error
from services import calc
from services.common import (
    field_datetime,
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

DISCIPLINES = ("CYCLING", "RUNNING", "STRENGTH", "YOGA")
DELIVERY_MODES = ("LIVE", "ON_DEMAND")
BENCHMARK_VARIANTS = ("STRICT_BENCHMARK", "INDULGENT_BENCHMARK")

SESSION_TERMINAL = ("ARCHIVED", "CANCELLED")
OPEN_ENROLLMENT_STATES = ("ENROLLED", "WAITLISTED")


# ---------------------------------------------------------------------------
# ClassSession
# ---------------------------------------------------------------------------
def create_session(payload):
    reject_unknown(
        payload,
        {"title", "instructor_name", "discipline", "delivery_mode", "starts_at",
         "ends_at", "capacity", "license_starts_at", "license_ends_at"},
    )
    title = field_str(payload, "title")
    instructor_name = field_str(payload, "instructor_name")
    discipline = field_enum(payload, "discipline", DISCIPLINES)
    delivery_mode = field_enum(payload, "delivery_mode", DELIVERY_MODES)
    starts_at = field_datetime(payload, "starts_at")
    ends_at = field_datetime(payload, "ends_at")
    capacity = field_int(payload, "capacity", required=False, default=100, minimum=0)
    license_starts_at = field_datetime(payload, "license_starts_at")
    license_ends_at = field_datetime(payload, "license_ends_at")

    # The draft step only sanity-checks the licensing window; full containment
    # is enforced at publish time (PRD section 3.8).
    if license_starts_at >= starts_at or license_ends_at <= license_starts_at:
        raise api_error(
            "ERR_LICENSE_WINDOW_INVALID",
            "The licensing window must start before the session start and end after its own start.",
        )

    if db.sessions_by_instructor_overlap(
        instructor_name, starts_at, ends_at, ("PUBLISHED", "STREAMING")
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The instructor already holds an open session covering this half-open window.",
        )

    return db.create("class_sessions", {
        "title": title,
        "instructor_name": instructor_name,
        "discipline": discipline,
        "delivery_mode": delivery_mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "license_starts_at": license_starts_at,
        "license_ends_at": license_ends_at,
        "scheduled_status": "DRAFT",
        "live_enrollment_count": 0,
        "on_demand_window_ends_at": None,
    })


def publish(session):
    if session["scheduled_status"] in SESSION_TERMINAL:
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The session has reached a terminal state and admits no further transition.",
        )
    if session["scheduled_status"] != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Only a DRAFT session may be published.")

    if session["delivery_mode"] == "LIVE":
        # The whole live window must sit inside the licensing window.  This is
        # the containment gate the draft step deliberately defers.
        if (
            session["starts_at"] < session["license_starts_at"]
            or session["ends_at"] > session["license_ends_at"]
        ):
            raise api_error(
                "ERR_LICENSE_WINDOW_INVALID",
                "A LIVE session must sit entirely inside its licensing window.",
            )
    else:
        # The library window is clamped to the licence so it never outlives the
        # instructor's rights.
        window_end = session["ends_at"] + clock.hours(24)
        session["on_demand_window_ends_at"] = min(window_end, session["license_ends_at"])

    # A publish that would stream through a window the instructor already holds
    # is refused; both open windows are half-open, so touching is not overlap.
    if db.open_session_overlap_after_publish(
        session["instructor_name"], session["starts_at"], session["ends_at"], session["id"]
    ):
        raise api_error(
            "ERR_TEMPORAL_OVERLAP",
            "The instructor already holds an open session covering this half-open window.",
        )

    session["scheduled_status"] = "PUBLISHED"
    db.touch(session)
    return session


def cancel_session(session):
    if session["scheduled_status"] in SESSION_TERMINAL:
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The session has reached a terminal state and admits no further transition.",
        )
    if session["scheduled_status"] != "PUBLISHED":
        raise api_error("ERR_INVALID_STATE", "Only a PUBLISHED session may be cancelled.")

    session["scheduled_status"] = "CANCELLED"
    for enrollment in db.STORE["class_enrollments"].values():
        if enrollment["class_session_id"] != session["id"]:
            continue
        if enrollment["status"] in OPEN_ENROLLMENT_STATES:
            enrollment["status"] = "DROPPED"
            db.touch(enrollment)
    calc.recompute_enrollment_count(session)
    db.touch(session)
    return session


def leaderboard(session):
    """Computed read of the integrity-capped leaderboard (no version bump)."""
    entries = []
    for enrollment in db.STORE["class_enrollments"].values():
        if enrollment["class_session_id"] != session["id"]:
            continue
        if enrollment["status"] != "COMPLETED":
            continue
        entries.append({
            "enrollment_id": enrollment["id"],
            "device_id": enrollment["device_id"],
            "enroller_user_id": enrollment["enroller_user_id"],
            "discipline": session["discipline"],
            "points_per_pct": calc.points_per_pct(session),
            "output_points": enrollment["output_points"],
            "integrity_points": enrollment["integrity_points"],
            "integrity_flagged": enrollment["integrity_flagged"],
            "completion_pct": enrollment["completion_pct"],
            "completion_grade": enrollment["completion_grade"],
        })
    entries.sort(key=lambda entry: (-entry["integrity_points"], entry["enrollment_id"]))
    return {
        "session_id": session["id"],
        "entries": entries,
        "integrity_flagged_count": sum(1 for e in entries if e["integrity_flagged"]),
        "total_points": sum(e["integrity_points"] for e in entries),
    }


# ---------------------------------------------------------------------------
# ClassEnrollment
# ---------------------------------------------------------------------------
def _cascade_expire(session, statuses, to_status, only_zero_completion=False):
    count = 0
    for enrollment in db.STORE["class_enrollments"].values():
        if enrollment["class_session_id"] != session["id"]:
            continue
        if enrollment["status"] not in statuses:
            continue
        if only_zero_completion and enrollment["completion_pct"] != 0:
            continue
        enrollment["status"] = to_status
        db.touch(enrollment)
        count += 1
    return count


def _refresh_membership_for_session(session):
    """Recompute the posture of every membership owning an affected device."""
    seen = set()
    for enrollment in db.STORE["class_enrollments"].values():
        if enrollment["class_session_id"] != session["id"]:
            continue
        device = db.STORE["devices"].get(enrollment["device_id"])
        if device is None or device["membership_id"] is None:
            continue
        if device["membership_id"] in seen:
            continue
        seen.add(device["membership_id"])
        membership = db.STORE["memberships"].get(device["membership_id"])
        if membership is not None:
            calc.recompute_membership(membership, bump=False)


def archive(session, mode):
    """PUBLISHED or STREAMING -> ARCHIVED with its enrollment cascade."""
    session["scheduled_status"] = "ARCHIVED"
    if mode == "STREAMING":
        # Only ENROLLED enrollments with nothing completed are dropped.
        _cascade_expire(session, ("ENROLLED",), "DROPPED", only_zero_completion=True)
    else:
        _cascade_expire(session, ("ENROLLED",), "EXPIRED")
        _cascade_expire(session, ("WAITLISTED",), "EXPIRED")
    calc.recompute_enrollment_count(session)
    db.touch(session)
    _refresh_membership_for_session(session)
    return session


def enroll(payload):
    reject_unknown(payload, {"class_session_id", "device_id", "enroller_user_id"})
    class_session_id = field_str(payload, "class_session_id")
    device_id = field_str(payload, "device_id")
    enroller_user_id = field_str(payload, "enroller_user_id")

    session = db.require("class_sessions", class_session_id)
    device = db.require("devices", device_id)
    user = db.require("household_users", enroller_user_id)

    if device["membership_id"] != user["membership_id"]:
        raise api_error(
            "ERR_DEVICE_NOT_ON_MEMBERSHIP",
            "The device does not belong to the enroller's membership.",
        )
    if not device["content_access_allowed"]:
        raise api_error(
            "ERR_CONTENT_LOCKED",
            "The device's content_access_allowed is false.",
        )

    # ERR_CLASS_CAPACITY_EXCEEDED covers a session that is not in a publishable
    # state and an on-demand enrollment attempted outside its library window.
    # A LIVE session that has simply reached its capacity is not refused: the
    # enrollment is admitted, just as WAITLISTED.
    if session["delivery_mode"] == "LIVE":
        if session["scheduled_status"] not in ("PUBLISHED", "STREAMING"):
            raise api_error(
                "ERR_CLASS_CAPACITY_EXCEEDED",
                "The session is not in a publishable state.",
            )
    else:
        if session["scheduled_status"] not in ("PUBLISHED", "STREAMING"):
            raise api_error(
                "ERR_CLASS_CAPACITY_EXCEEDED",
                "The session is not in a publishable state.",
            )
        window_end = session["on_demand_window_ends_at"]
        if window_end is None or clock.now() >= window_end:
            raise api_error(
                "ERR_CLASS_CAPACITY_EXCEEDED",
                "The on-demand library window is closed.",
            )

    # The session's open-enrollment figure drives both the capacity test and
    # the waitlist, for either delivery mode.
    calc.recompute_enrollment_count(session)
    at_capacity = session["live_enrollment_count"] >= session["capacity"]

    enrollment = db.create("class_enrollments", {
        "class_session_id": class_session_id,
        "device_id": device_id,
        "enroller_user_id": enroller_user_id,
        "enrolled_at": clock.now(),
        "status": "WAITLISTED" if at_capacity else "ENROLLED",
        "output_points": 0,
        "integrity_points": 0,
        "integrity_flagged": False,
        "completion_pct": 0,
        "completion_grade": None,
    })

    calc.recompute_enrollment_count(session)
    # A seat opened by a concurrency eviction on the session is what lets a
    # waiter come back in; recomputing the count may reveal one.
    promote_waitlisted(session)
    return enrollment


def promote_waitlisted(session, limit_promotions=None):
    """WAITLISTED -> ENROLLED for the earliest by enrolled_at ASC, then created_at."""
    promoted = 0
    while True:
        if limit_promotions is not None and promoted >= limit_promotions:
            break
        calc.recompute_enrollment_count(session)
        if session["live_enrollment_count"] >= session["capacity"]:
            break
        waiters = [
            enrollment
            for enrollment in db.STORE["class_enrollments"].values()
            if enrollment["class_session_id"] == session["id"]
            and enrollment["status"] == "WAITLISTED"
        ]
        if not waiters:
            break
        waiters.sort(key=lambda enrollment: (enrollment["enrolled_at"], enrollment.created_at))
        chosen = waiters[0]
        chosen["status"] = "ENROLLED"
        db.touch(chosen)
        promoted += 1
        calc.recompute_enrollment_count(session)
    return promoted


def demote_to_waitlist(session, enrollment):
    """ENROLLED -> WAITLISTED when the open count has reached capacity."""
    calc.recompute_enrollment_count(session)
    if enrollment["status"] != "ENROLLED":
        raise api_error("ERR_INVALID_STATE", "Only an ENROLLED seat may be waitlisted.")
    if session["live_enrollment_count"] < session["capacity"]:
        raise api_error(
            "ERR_INVALID_STATE",
            "The session has not reached its capacity, so no seat is reclaimed.",
        )
    enrollment["status"] = "WAITLISTED"
    db.touch(enrollment)
    calc.recompute_enrollment_count(session)
    return enrollment


def complete(enrollment, payload):
    reject_unknown(payload, {"output_points", "completion_pct", "benchmark_variant"})
    session = db.require("class_sessions", enrollment["class_session_id"])
    device = db.require("devices", enrollment["device_id"])

    if enrollment["status"] != "ENROLLED":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only an ENROLLED enrollment may be completed.",
        )
    if not device["content_access_allowed"]:
        raise api_error(
            "ERR_CONTENT_LOCKED",
            "The device's content_access_allowed is false.",
        )
    if session["scheduled_status"] not in ("PUBLISHED", "STREAMING", "ARCHIVED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "The session is not in a state that admits a completion.",
        )

    output_points = field_int(payload, "output_points", required=False, default=0, minimum=0)
    completion_pct = field_int(payload, "completion_pct", required=False, default=0, minimum=0)
    variant = field_enum(
        payload, "benchmark_variant", BENCHMARK_VARIANTS,
        required=False, default="STRICT_BENCHMARK",
    )

    points, flagged, _benchmark = calc.integrity_points(session, output_points, variant)

    enrollment["status"] = "COMPLETED"
    enrollment["output_points"] = output_points
    enrollment["completion_pct"] = completion_pct
    enrollment["completion_grade"] = "FULL_CREDIT" if completion_pct >= 80 else "PARTIAL_CREDIT"
    enrollment["integrity_flagged"] = flagged
    enrollment["integrity_points"] = points
    db.touch(enrollment)

    device["total_workouts"] = device["total_workouts"] + 1
    db.touch(device)

    calc.recompute_enrollment_count(session)

    membership = db.STORE["memberships"].get(device["membership_id"])
    if membership is not None:
        calc.recompute_membership(membership, bump=False)

    return enrollment


def drop(enrollment):
    if enrollment["status"] not in OPEN_ENROLLMENT_STATES:
        raise api_error(
            "ERR_INVALID_STATE",
            "Only an ENROLLED or WAITLISTED enrollment may be dropped.",
        )
    session = db.require("class_sessions", enrollment["class_session_id"])
    enrollment["status"] = "DROPPED"
    db.touch(enrollment)
    calc.recompute_enrollment_count(session)
    return enrollment


def owned_by(caller, enrollment):
    user = db.STORE["household_users"].get(enrollment["enroller_user_id"])
    membership_id = user["membership_id"] if user is not None else None
    if caller.is_owner and membership_id is not None and membership_id != caller.user_id:
        raise api_error("ERR_UNAUTHORIZED")
    return enrollment