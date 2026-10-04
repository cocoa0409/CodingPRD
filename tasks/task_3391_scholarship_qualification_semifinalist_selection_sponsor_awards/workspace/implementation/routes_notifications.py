"""Notification endpoints: per-student list (sequence_number ASC) and
manual release with sequencing, embargo, and publicity-gap gates."""

from datetime import timedelta

from flask import Blueprint, g, request

import constants as C
from errors import err
from helpers import apply_filters, paginate, require_roles, resp_object
from serializers import ser_notification
from store import clock_now, db, iso_z, parse_dt, touch

bp = Blueprint("notifications", __name__)


@bp.route("/api/students/<student_id>/notifications", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_STUDENT)
def list_student_notifications(student_id):
    # Student acts only on own records (path id vs X-User-ID, priority 3).
    if g.user_role == C.ROLE_STUDENT and g.user_id != student_id:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only read their own notifications")
    if student_id not in db["students"]:
        err("ERR_NOT_FOUND", "student not found")
    records = [n for n in db["notifications"].values() if n["student_id"] == student_id]
    records = apply_filters(
        records,
        [
            ("status", request.args.get("status")),
            ("notice_type", request.args.get("notice_type")),
        ],
    )
    records.sort(key=lambda n: (n["sequence_number"], n["created_at"], n["_seq"]))
    return paginate(records, ser_notification)


@bp.route("/api/notifications/<notification_id>/release", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def release_notification(notification_id):
    rec = db["notifications"].get(notification_id)
    if rec is None:
        err("ERR_NOT_FOUND", "notification not found")
    # Priority 6, entity state: only EMBARGOED may be released (manual-only).
    if rec["status"] != "EMBARGOED":
        err("ERR_INVALID_STATE", "notification is not EMBARGOED")
    now = clock_now()
    # Priority 7, per-student release order: every notification of the same
    # student with a lower sequence_number must already be RELEASED.
    for n in db["notifications"].values():
        if (
            n["student_id"] == rec["student_id"]
            and n["sequence_number"] < rec["sequence_number"]
            and n["status"] != "RELEASED"
        ):
            err(
                "ERR_NOTIFICATION_SEQUENCE_VIOLATION",
                "a lower-sequence notification of this student is not released",
            )
    # Priority 8, embargo: logical clock at or past embargo_until.
    if now < parse_dt(rec["embargo_until"]):
        err("ERR_NOTIFICATION_EMBARGOED", "notification is still embargoed")
    # Priority 8, publicity gap on PUBLIC_ANNOUNCEMENT: at least 2 days past
    # the most recent released AWARD_OFFER of the cycle.
    if rec["notice_type"] == "PUBLIC_ANNOUNCEMENT":
        released_offer_times = [
            parse_dt(n["released_logical_at"])
            for n in db["notifications"].values()
            if n["cycle_id"] == rec["cycle_id"]
            and n["notice_type"] == "AWARD_OFFER"
            and n["status"] == "RELEASED"
            and n["released_logical_at"] is not None
        ]
        if released_offer_times:
            earliest_allowed = max(released_offer_times) + timedelta(days=C.PUBLICITY_GAP_DAYS)
            if now < earliest_allowed:
                err("ERR_PUBLICITY_WINDOW_TOO_EARLY", "publicity gap has not elapsed")
    rec["status"] = "RELEASED"
    rec["released_logical_at"] = iso_z(now)
    touch(rec)
    return resp_object(ser_notification(rec))
