"""Mix stage bookings (PRD §3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, touch
from errors import ApiError

bp = Blueprint("bookings", __name__)

OCCUPYING_STATUSES = ("RESERVED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")
MIXER_DAILY_STATUSES = ("CONFIRMED", "IN_PROGRESS", "COMPLETED")


@bp.post("/mix-bookings")
def create_mix_booking():
    middleware.actor("PostSupervisor")
    payload = V.body()
    project = middleware.body_ref(payload, "project_id", db.projects)
    stage = middleware.body_ref(payload, "mix_stage_id", db.mix_stages)
    mixer = middleware.body_ref(payload, "mixer_id", db.mixers)
    expected = V.v_int(payload, "expected_project_version")
    V.v_string(payload, "project_id", minlen=1)
    V.v_string(payload, "mix_stage_id", minlen=1)
    V.v_string(payload, "mixer_id", minlen=1)
    booking_type = V.v_enum(payload, "booking_type", V.BOOKING_TYPES)
    platform = V.v_enum(payload, "platform", V.PLATFORMS)
    window_start = V.v_instant(payload, "window_start_utc")
    window_end = V.v_instant(payload, "window_end_utc")
    client_attendance = V.v_enum(payload, "client_attendance", V.CLIENT_ATTENDANCE,
                                required=False, default="NONE")

    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    middleware.gate_posture(project, "booking_create")
    middleware.gate_archived(project)
    if booking_type in ("FINAL_MIX", "PRINTMASTER"):
        middleware.gate_picture_locked(project)
    if platform not in mixer["certified_platforms"]:
        raise ApiError("ERR_MIXER_NOT_CERTIFIED")
    if client_attendance == "REMOTE" and not stage["supports_remote_review"]:
        raise ApiError("ERR_STAGE_NO_REMOTE_REVIEW")
    if window_end <= window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    if window_end > project["delivery_deadline_utc"]:
        raise ApiError("ERR_WINDOW_AFTER_DEADLINE")

    # Supersession set: excluded from both the occupancy and the stage-hours check.
    superseded = [b for b in derive.bookings_of(project["id"])
                  if b["booking_type"] == booking_type
                  and b["status"] in ("RESERVED", "CONFIRMED")]
    superseded_ids = {b["id"] for b in superseded}

    # Rung 33: the requested window extended by the changeover buffer on both sides.
    buffer = timedelta(minutes=stage["changeover_minutes"])
    extended_start = window_start - buffer
    extended_end = window_end + buffer
    for other in db.mix_bookings.values():
        if other["mix_stage_id"] != stage["id"] or other["id"] in superseded_ids:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if extended_start < other["window_end_utc"] and other["window_start_utc"] < extended_end:
            raise ApiError("ERR_STAGE_WINDOW_CONFLICT")

    requested_hours, reserved_hours, provisional = calc.provisional_booking_cost(
        window_start, window_end, stage["hourly_rate_cents"], project["turnaround_class"])

    # Rung 42: available hours with the superseded booking's hours already returned.
    reserved_other = Decimal("0.00")
    consumed = Decimal("0.00")
    for other in derive.bookings_of(project["id"]):
        if other["id"] in superseded_ids:
            continue
        if other["status"] in derive.RESERVING_BOOKING_STATUSES:
            reserved_other = reserved_other + other["reserved_hours"]
        elif other["status"] == "COMPLETED":
            consumed = consumed + (other["billable_hours_final"] or Decimal("0.00"))
    available = calc.q2(project["stage_hours_authorized"] - reserved_other - consumed)
    if reserved_hours > available:
        raise ApiError("ERR_STAGE_HOURS_EXCEEDED")

    for old in superseded:
        old["status"] = "SUPERSEDED"
        touch(old)

    record = new_record()
    record.update({
        "project_id": project["id"],
        "mix_stage_id": stage["id"],
        "mixer_id": mixer["id"],
        "booking_type": booking_type,
        "platform": platform,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "client_attendance": client_attendance,
        "status": "RESERVED",
        "reserved_hours": reserved_hours,
        "provisional_cost_cents": provisional,
        "actual_start_utc": None,
        "actual_end_utc": None,
        "billable_hours_final": None,
        "overtime_hours": None,
        "final_cost_cents": None,
        "client_signoff_at_utc": None,
        "release_reason": None,
    })
    db.mix_bookings[record["id"]] = record

    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.mix_booking(record), 201)


@bp.get("/mix-bookings/<booking_id>")
def read_mix_booking(booking_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer",
                     "QcOperator", "ClientReviewer")
    record = middleware.path_mix_booking(booking_id)
    return response.object_response(serialize.mix_booking(record))


@bp.get("/mix-bookings")
def list_mix_bookings():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    limit, offset = V.pagination()
    project_id = V.query_filter("project_id")
    mix_stage_id = V.query_filter("mix_stage_id")
    mixer_id = V.query_filter("mixer_id")
    status = V.query_filter("status")
    records = list(db.mix_bookings.values())
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if mix_stage_id is not None:
        records = [r for r in records if r["mix_stage_id"] == mix_stage_id]
    if mixer_id is not None:
        records = [r for r in records if r["mixer_id"] == mixer_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.mix_booking(r) for r in window],
                                  limit, offset, total)


@bp.post("/mix-bookings/<booking_id>/confirm")
def confirm_mix_booking(booking_id):
    """PRD §3.6: RESERVED -> CONFIRMED by the assigned mixer only."""
    user_id, _role = middleware.actor("Mixer")
    booking = middleware.path_mix_booking(booking_id)
    middleware.require_assigned_mixer(user_id, booking)
    project = db.projects.get(booking["project_id"])
    middleware.gate_posture(project, "booking_confirm")
    middleware.gate_archived(project)
    if booking["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")

    mixer = db.mixers.get(booking["mixer_id"])
    day = booking["window_start_utc"].date()
    same_day = Decimal("0.00")
    for other in db.mix_bookings.values():
        if other["mixer_id"] != booking["mixer_id"] or other["id"] == booking["id"]:
            continue
        if other["status"] not in MIXER_DAILY_STATUSES:
            continue
        if other["window_start_utc"].date() != day:
            continue
        same_day = same_day + other["reserved_hours"]
    if same_day + booking["reserved_hours"] > mixer["max_daily_hours"]:
        raise ApiError("ERR_MIXER_DAILY_LIMIT_EXCEEDED")

    booking["status"] = "CONFIRMED"
    touch(booking)
    if booking["booking_type"] == "FINAL_MIX":
        derive.advance_pipeline(project, "PREMIX", "FINAL_MIX")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.mix_booking(booking))


@bp.post("/mix-bookings/<booking_id>/start")
def start_mix_booking(booking_id):
    """PRD §3.6: CONFIRMED -> IN_PROGRESS, only strictly before window_end_utc."""
    user_id, _role = middleware.actor("Mixer")
    booking = middleware.path_mix_booking(booking_id)
    middleware.require_assigned_mixer(user_id, booking)
    project = db.projects.get(booking["project_id"])
    middleware.gate_posture(project, "booking_start")
    middleware.gate_archived(project)
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() >= booking["window_end_utc"]:
        raise ApiError("ERR_WINDOW_ELAPSED")

    booking["status"] = "IN_PROGRESS"
    booking["actual_start_utc"] = clock.now()
    touch(booking)
    return response.object_response(serialize.mix_booking(booking))


@bp.post("/mix-bookings/<booking_id>/complete")
def complete_mix_booking(booking_id):
    """PRD §3.6: IN_PROGRESS -> COMPLETED, pinning the FINAL cost variant."""
    user_id, _role = middleware.actor("Mixer")
    booking = middleware.path_mix_booking(booking_id)
    middleware.require_assigned_mixer(user_id, booking)
    project = db.projects.get(booking["project_id"])
    middleware.gate_posture(project, "booking_complete")
    middleware.gate_archived(project)
    if booking["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    if booking["client_attendance"] == "REMOTE" and booking["client_signoff_at_utc"] is None:
        raise ApiError("ERR_CLIENT_SIGNOFF_REQUIRED")

    stage = db.mix_stages.get(booking["mix_stage_id"])
    actual_end = clock.now()
    billable, overtime, final_cost = calc.final_booking_cost(
        booking["actual_start_utc"], actual_end, booking["reserved_hours"],
        stage["hourly_rate_cents"], project["turnaround_class"])
    booking["status"] = "COMPLETED"
    booking["actual_end_utc"] = actual_end
    booking["billable_hours_final"] = billable
    booking["overtime_hours"] = overtime
    booking["final_cost_cents"] = final_cost
    touch(booking)

    if booking["booking_type"] == "FINAL_MIX":
        derive.advance_pipeline(project, "FINAL_MIX", "QC")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.mix_booking(booking))


@bp.post("/mix-bookings/<booking_id>/client-signoff")
def client_signoff(booking_id):
    """PRD §3.6: a field mutation only — the booking's status does not change."""
    user_id, role = middleware.actor("ClientReviewer")
    booking = middleware.path_mix_booking(booking_id)
    project = db.projects.get(booking["project_id"])
    middleware.require_project_client(user_id, role, project)
    if booking["status"] not in ("CONFIRMED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE")
    if booking["client_attendance"] != "REMOTE":
        raise ApiError("ERR_INVALID_STATE")
    stage = db.mix_stages.get(booking["mix_stage_id"])
    if not stage["supports_remote_review"]:
        raise ApiError("ERR_STAGE_NO_REMOTE_REVIEW")
    if booking["client_signoff_at_utc"] is not None:
        raise ApiError("ERR_ALREADY_SIGNED_OFF")

    booking["client_signoff_at_utc"] = clock.now()
    touch(booking)
    return response.object_response(serialize.mix_booking(booking))


@bp.post("/mix-bookings/<booking_id>/release")
def release_mix_booking(booking_id):
    """PRD §3.6: RESERVED|CONFIRMED -> RELEASED, a compensating ledger reversal."""
    middleware.actor("PostSupervisor")
    booking = middleware.path_mix_booking(booking_id)
    payload = V.body()
    reason = V.v_string(payload, "release_reason", minlen=1)
    project = db.projects.get(booking["project_id"])
    middleware.gate_archived(project)
    if booking["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")

    booking["status"] = "RELEASED"
    booking["release_reason"] = reason
    touch(booking)
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.mix_booking(booking))
