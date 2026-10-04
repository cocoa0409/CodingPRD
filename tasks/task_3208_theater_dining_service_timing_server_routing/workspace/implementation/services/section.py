"""Server profiles, shifts, the quality index, and section rostering."""

from datetime import timedelta
from decimal import Decimal

import db
import errors
from errors import ApiError
from services import core

NON_TERMINAL = ("DRAFT", "ACTIVE", "REASSIGNMENT_PENDING")


def create_server(data):
    aud = core.auditorium(data.get("home_auditorium_id"))
    row = {
        "display_name": data.get("display_name") or "",
        "home_auditorium_id": aud["id"],
        "ratings": [],
        "lifetime_points": 0,
        "in_rotation": True,
        "shift_load_projected": 0,
        "shift_load_final": 0,
        "rollup_provisional_cents": 0,
        "quality_index": 0.0,
        "status": "ACTIVE",
        "version": 1,
        "updated_at": db.db.now,
    }
    db.db.register("servers", row)
    core.refresh_server(row)
    return row


def _on_floor(st):
    return (st["dining_open_at_utc"], st["start_at_utc"])


def _separation_ok(srv, st, ignore_assignment_id=None):
    """CLOSED on-floor intervals, rejecting any pair closer than the buffer.

    PRD 2.11: two of a server's active assignments, in any auditoriums, whose
    on-floor intervals are separated by less than SERVO_BUFFER_MINUTES are
    rejected; a separation of exactly fifteen minutes is admitted. An interval
    that overlaps another has a separation of zero and is rejected outright.
    """
    new_start, new_end = _on_floor(st)
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if a["status"] != "ACTIVE":
            continue
        if ignore_assignment_id is not None and a["id"] == ignore_assignment_id:
            continue
        other = db.db.showtimes.get(a["showtime_id"])
        if other is None:
            continue
        o_start, o_end = _on_floor(other)
        if new_start <= o_end and o_start <= new_end:
            return False
        if new_start > o_end:
            gap = (new_start - o_end).total_seconds() / 60.0
        else:
            gap = (o_start - new_end).total_seconds() / 60.0
        if gap < core.SERVO_BUFFER_MINUTES:
            return False
    return True


def _projected_after_add(srv, new_assignment_status="ACTIVE"):
    day = db.db.now.date()
    count = 0
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if core.service_day(a) != day:
            continue
        if a["status"] == "CANCELLED":
            continue
        count += 1
    return count + 1


def _occupancy_ok(srv, st, section_label, ignore_assignment_id=None):
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if a["status"] not in NON_TERMINAL:
            continue
        if ignore_assignment_id is not None and a["id"] == ignore_assignment_id:
            continue
        if a["auditorium_id"] != st["auditorium_id"]:
            continue
        if a["section_label"] == section_label:
            return False
    return True


def create_assignment(data):
    st = core.showtime(data.get("showtime_id"))
    srv = core.server(data.get("server_id"))
    section_label = data.get("section_label")
    if section_label is None:
        section_label = ""

    if not _separation_ok(srv, st):
        raise ApiError(errors.ERR_SERVER_SECTION_OVERLAP)
    if _projected_after_add(srv) > core.DAILY_SECTION_CAP:
        raise ApiError(errors.ERR_SERVER_HARD_CAP_EXCEEDED)
    if not _occupancy_ok(srv, st, section_label):
        raise ApiError(errors.ERR_SECTION_OCCUPIED)

    row = {
        "showtime_id": st["id"],
        "auditorium_id": st["auditorium_id"],
        "server_id": srv["id"],
        "section_label": section_label,
        "status": "ACTIVE",
        "version": 1,
        "assignment_points": 0,
        "auto_completed": False,
        "rating_grade": None,
        "updated_at": db.db.now,
    }
    db.db.register("section_assignments", row)
    core.bump_version(srv)
    core.refresh_server(srv)
    return row


def reassign(a, data):
    expected = data.get("expected_section_assignment_version")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = -1
        if expected != a["version"]:
            raise ApiError(errors.ERR_STALE_SECTION_ASSIGNMENT_VERSION)

    if a["status"] != "ACTIVE":
        raise ApiError(errors.ERR_SECTION_ASSIGNMENT_NOT_ACTIVE)

    incoming = core.server(data.get("server_id"))
    st = core.showtime(a["showtime_id"])
    if not _separation_ok(incoming, st, ignore_assignment_id=a["id"]):
        raise ApiError(errors.ERR_SERVER_SECTION_OVERLAP)
    if _projected_after_add(incoming) > core.DAILY_SECTION_CAP:
        raise ApiError(errors.ERR_SERVER_HARD_CAP_EXCEEDED)
    if not _occupancy_ok(incoming, st, a["section_label"], ignore_assignment_id=a["id"]):
        raise ApiError(errors.ERR_SECTION_OCCUPIED)

    outgoing = db.db.servers.get(a["server_id"])
    a["status"] = "REASSIGNMENT_PENDING"
    a["server_id"] = incoming["id"]
    a["status"] = "ACTIVE"
    core.bump_version(a)
    core.touch(a)
    for srv in (incoming, outgoing):
        if srv is not None:
            core.bump_version(srv)
            core.refresh_server(srv)
    return a


def score(a, data):
    grade = data.get("rating_grade")
    if grade not in ("A", "B", "C"):
        grade = "C"
    a["rating_grade"] = grade
    core.touch(a)
    srv = db.db.servers.get(a["server_id"])
    if srv is not None:
        srv["quality_index"] = core.server_quality_index(srv)
        core.bump_version(srv)
        core.touch(srv)
    return a


def close(a):
    if a["status"] not in ("ACTIVE", "REASSIGNMENT_PENDING"):
        raise ApiError(errors.ERR_SECTION_ASSIGNMENT_NOT_ACTIVE)
    a["status"] = "COMPLETED"
    points = core.assignment_points(a)
    a["assignment_points"] = points
    core.bump_version(a)
    core.touch(a)
    srv = db.db.servers.get(a["server_id"])
    if srv is not None:
        srv["lifetime_points"] = srv["lifetime_points"] + points
        st = db.db.showtimes.get(a["showtime_id"])
        if st is not None and not core.showtime_has_ejection_refund(st) \
                and a.get("rating_grade"):
            srv["ratings"].append({"assignment_id": a["id"],
                                   "rating_grade": a["rating_grade"]})
        core.bump_version(srv)
        core.refresh_server_status(srv)
        core.refresh_server(srv)
    return a


def cancel(a):
    if a["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errors.ERR_SECTION_ASSIGNMENT_NOT_ACTIVE)
    a["status"] = "CANCELLED"
    a["assignment_points"] = core.assignment_points(a, cancel=True)
    core.bump_version(a)
    core.touch(a)
    srv = db.db.servers.get(a["server_id"])
    if srv is not None:
        core.bump_version(srv)
        core.refresh_server_status(srv)
        core.refresh_server(srv)
    return a


def shift_start(srv):
    srv["shift_load_projected"] = core.projected_load(srv)
    core.touch(srv)
    core.bump_version(srv)
    return srv


def shift_end(srv):
    srv["shift_load_projected"] = core.projected_load(srv)
    srv["shift_load_final"] = core.final_load(srv)
    srv["quality_index"] = core.server_quality_index(srv)
    core.touch(srv)
    core.bump_version(srv)
    return srv


def rate(srv, data):
    assignment_id = data.get("assignment_id")
    grade = data.get("rating_grade")
    if grade not in ("A", "B", "C"):
        grade = "C"
    srv["ratings"].append({"assignment_id": assignment_id, "rating_grade": grade})
    srv["quality_index"] = core.server_quality_index(srv)
    core.touch(srv)
    core.bump_version(srv)
    return srv


def clear_penalty(srv):
    if not srv["status"] == "PENALIZED" and srv["in_rotation"]:
        raise ApiError(errors.ERR_SERVER_NOT_PENALIZED)
    srv["status"] = "ACTIVE"
    srv["in_rotation"] = True
    core.touch(srv)
    core.bump_version(srv)
    return srv