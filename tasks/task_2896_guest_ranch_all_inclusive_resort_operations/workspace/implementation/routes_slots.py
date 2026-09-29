"""Activity slots, their lifecycle and the guides who staff them (PRD 3.7)."""

import datetime

from flask import Blueprint

import calc
import derive
import fields
from auth import ALL_OPERATIONAL, EVERYONE, auth
from derive import Touch, assignment_json, slot_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find, find_body_ref
from store import db

bp = Blueprint("slots", __name__)

ACTIVITY_TYPES = ("TRAIL_RIDE", "ARENA_LESSON", "FLY_FISHING", "HIKE", "KIDS_PROGRAM")
TERRAIN_GRADES = ("MEADOW", "ROLLING", "STEEP", "RIVER_CROSSING")
SLOT_STATUSES = ("DRAFT", "OPEN", "HOLD", "RUNNING", "COMPLETED", "CANCELLED")
GUIDE_ROLES = ("LEAD", "ASSISTANT", "WRANGLER")
ASSIGNMENT_STATUSES = ("SCHEDULED", "RELEASED", "COMPLETED")
ASSIGNMENT_READERS = ("RanchManager", "ActivityGuide", "SafetyOfficer", "ReservationsAgent")


def assigned_guide_or_403(slot, user_id):
    """Precedence rule 5: an ActivityGuide must hold a SCHEDULED assignment here."""
    for assignment in derive.assignments_of_slot(slot["id"]):
        if (
            assignment["staff_member_id"] == user_id
            and assignment["assignment_status"] == "SCHEDULED"
        ):
            return assignment
    raise ApiError(
        "ERR_NOT_ASSIGNED_GUIDE",
        "The acting guide holds no SCHEDULED assignment on this slot.",
    )


@bp.post("/seasons/<season_id>/activity-slots")
def create_slot(season_id):
    auth("RanchManager")
    season = find("seasons", season_id)
    data = body()
    require(
        data,
        "activity_type",
        "starts_at",
        "ends_at",
        "terrain_grade",
        "min_ability_rank",
        "capacity",
    )
    activity_type = fields.as_enum(data, "activity_type", ACTIVITY_TYPES)
    starts_at = fields.as_instant(data, "starts_at")
    ends_at = fields.as_instant(data, "ends_at")
    terrain = fields.as_enum(data, "terrain_grade", TERRAIN_GRADES)
    min_rank = fields.as_enum(data, "min_ability_rank", calc.ALL_RANKS)
    capacity = fields.as_int(data, "capacity", minimum=1)
    surcharge = fields.as_cents(data, "rider_surcharge_cents", default=0)
    fields.as_bool(data, "mount_required")

    if season["season_status"] not in ("OPEN", "IN_SEASON"):
        raise ApiError(
            "ERR_SEASON_NOT_OPEN",
            "Slots may only be scheduled inside an OPEN or IN_SEASON season.",
        )
    if ends_at <= starts_at or starts_at.date() != ends_at.date():
        raise ApiError(
            "ERR_SLOT_OUTSIDE_SEASON",
            "A slot must end after it starts, on the same calendar date.",
        )
    if (
        starts_at.date() < season["season_start_date"]
        or ends_at.date() > season["season_end_date"]
    ):
        raise ApiError(
            "ERR_SLOT_OUTSIDE_SEASON",
            "The slot interval falls outside the season window.",
        )

    duration = calc.hours((ends_at - starts_at).total_seconds() / 3600.0, 2)
    row = db.insert(
        "activity_slots",
        {
            "season_id": season["id"],
            "activity_type": activity_type,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "duration_hours": duration,
            "terrain_grade": terrain,
            "min_ability_rank": min_rank,
            "capacity": capacity,
            "rider_surcharge_cents": surcharge,
            "mount_required": activity_type in calc.MOUNTED_ACTIVITIES,
            "slot_status": "DRAFT",
            "hold_reason": None,
            "actual_started_at": None,
            "actual_ended_at": None,
            "actual_duration_hours": None,
        },
    )
    return created(slot_json(row))


@bp.get("/activity-slots/<slot_id>")
def read_slot(slot_id):
    auth(*EVERYONE)
    return ok(slot_json(find("activity_slots", slot_id)))


@bp.get("/activity-slots")
def list_slots():
    auth(*ALL_OPERATIONAL)
    rows = derive.rows_of(
        "activity_slots",
        season_id=fields.query_filter("season_id"),
        activity_type=fields.query_enum("activity_type", ACTIVITY_TYPES),
        slot_status=fields.query_enum("slot_status", SLOT_STATUSES),
    )
    return listing(rows, slot_json)


@bp.post("/activity-slots/<slot_id>/open")
def open_slot(slot_id):
    auth("RanchManager")
    slot = find("activity_slots", slot_id)
    season = db.seasons.get(slot["season_id"])
    if season is None or season["season_status"] not in ("OPEN", "IN_SEASON"):
        raise ApiError(
            "ERR_SEASON_NOT_OPEN", "Opening a slot requires an OPEN or IN_SEASON season."
        )
    if slot["slot_status"] not in ("DRAFT", "HOLD"):
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "A %s slot cannot be opened." % slot["slot_status"],
        )
    state = derive.slot_state(slot)
    if state["assigned_guide_count"] < 1 or state["readiness_posture"] != "STAFFED_READY":
        raise ApiError(
            "ERR_GUIDE_RATIO_UNMET",
            "The slot is not staffed and mounted for booking.",
        )

    slot["slot_status"] = "OPEN"
    slot["hold_reason"] = None
    db.touch(slot)
    return ok(slot_json(slot))


@bp.post("/activity-slots/<slot_id>/run")
def run_slot(slot_id):
    user_id, role = auth("ActivityGuide")
    slot = find("activity_slots", slot_id)
    assigned_guide_or_403(slot, user_id)
    season = db.seasons.get(slot["season_id"])
    if season is None or season["season_status"] != "IN_SEASON":
        raise ApiError("ERR_SEASON_NOT_OPEN", "Running a slot requires an IN_SEASON season.")
    if slot["slot_status"] != "OPEN":
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "Only an OPEN slot may be run; this one is %s." % slot["slot_status"],
        )
    state = derive.slot_state(slot)
    if state["assigned_guide_count"] < state["required_guide_count"]:
        raise ApiError(
            "ERR_GUIDE_RATIO_UNMET",
            "The slot needs %d guides and holds %d."
            % (state["required_guide_count"], state["assigned_guide_count"]),
        )
    if slot["mount_required"] and state["mount_assigned_count"] < state["confirmed_rider_count"]:
        raise ApiError(
            "ERR_MOUNTS_INCOMPLETE", "A confirmed rider on this slot has no mount."
        )
    if db.clock_instant() < slot["starts_at"]:
        raise ApiError("ERR_SLOT_NOT_STARTED", "The slot's start time has not arrived.")

    slot["slot_status"] = "RUNNING"
    slot["actual_started_at"] = db.clock_instant()
    db.touch(slot)
    return ok(slot_json(slot))


@bp.post("/activity-slots/<slot_id>/complete")
def complete_slot(slot_id):
    user_id, role = auth("ActivityGuide")
    slot = find("activity_slots", slot_id)
    assigned_guide_or_403(slot, user_id)
    data = body()
    require(data, "actual_duration_hours")
    raw_hours = fields.as_number(data, "actual_duration_hours", minimum=0)

    season = db.seasons.get(slot["season_id"])
    if season is None or season["season_status"] != "IN_SEASON":
        raise ApiError(
            "ERR_SEASON_NOT_OPEN", "Completing a slot requires an IN_SEASON season."
        )
    if slot["slot_status"] != "RUNNING":
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "Only a RUNNING slot may be completed; this one is %s." % slot["slot_status"],
        )

    duration = calc.hours(raw_hours, 2)
    slot["actual_duration_hours"] = duration
    if slot.get("actual_started_at") is not None:
        slot["actual_ended_at"] = slot["actual_started_at"] + datetime.timedelta(
            hours=duration
        )

    touch = Touch()
    duty_date = slot["starts_at"].date()
    duty_horse_ids = []
    for seat in derive.seats_of_slot(slot["id"]):
        if seat["reservation_status"] == "CHECKED_IN":
            seat["reservation_status"] = "COMPLETED"
            seat["completed_at"] = db.clock_iso()
            if seat.get("mount_status") == "ASSIGNED":
                seat["mount_status"] = "COMPLETED"
                horse_id = seat.get("assigned_horse_id")
                if horse_id is not None and horse_id not in duty_horse_ids:
                    duty_horse_ids.append(horse_id)
            touch.add(seat)
        elif seat["reservation_status"] == "CONFIRMED":
            seat["reservation_status"] = "NO_SHOW"
            booking = db.bookings.get(seat["booking_id"])
            if booking is not None:
                booking["no_show_count"] = int(booking["no_show_count"]) + 1
                booking["no_show_penalty_total_cents"] = int(
                    booking["no_show_count"]
                ) * int(season["no_show_penalty_cents"])
                touch.add(booking)
            derive.release_mount(seat, touch)
            touch.add(seat)

    for horse_id in duty_horse_ids:
        horse = db.horses.get(horse_id)
        if horse is None:
            continue
        horse["consecutive_duty_days"] = calc.next_duty_run(
            horse.get("last_duty_date"), horse["consecutive_duty_days"], duty_date
        )
        horse["last_duty_date"] = duty_date
        touch.add(horse)

    for assignment in derive.assignments_of_slot(slot["id"]):
        if assignment["assignment_status"] == "SCHEDULED":
            assignment["assignment_status"] = "COMPLETED"
            assignment["credited_hours"] = duration
            touch.add(assignment)

    slot["slot_status"] = "COMPLETED"
    touch.slot(slot)
    touch.finalize()
    return ok(slot_json(slot))


@bp.post("/activity-slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    auth("RanchManager")
    slot = find("activity_slots", slot_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    if slot["slot_status"] not in ("DRAFT", "OPEN", "HOLD"):
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "A %s slot cannot be cancelled." % slot["slot_status"],
        )

    touch = Touch()
    for seat in derive.seats_of_slot(slot["id"]):
        if seat["reservation_status"] in derive.LIVE_SEAT_STATUSES:
            derive.cancel_seat(seat, touch)
    for assignment in derive.assignments_of_slot(slot["id"]):
        if assignment["assignment_status"] == "SCHEDULED":
            assignment["assignment_status"] = "RELEASED"
            touch.add(assignment)
    slot["slot_status"] = "CANCELLED"
    slot["hold_reason"] = None
    touch.slot(slot)
    touch.finalize()
    return ok(slot_json(slot))


# ------------------------------------------------------------ guide assignments
@bp.post("/activity-slots/<slot_id>/guide-assignments")
def create_assignment(slot_id):
    auth("RanchManager")
    slot = find("activity_slots", slot_id)
    data = body()
    staff = find_body_ref("staff_members", data, "staff_member_id")
    require(data, "staff_member_id", "guide_role")
    fields.as_str(data, "staff_member_id")
    guide_role = fields.as_enum(data, "guide_role", GUIDE_ROLES)

    day = slot["starts_at"].date()
    day_hours = calc.dec(0)
    for other in db.rows("guide_assignments"):
        if other["staff_member_id"] != staff["id"]:
            continue
        if other["assignment_status"] != "SCHEDULED":
            continue
        other_slot = db.activity_slots.get(other["slot_id"])
        if other_slot is None:
            continue
        if calc.intervals_overlap(
            slot["starts_at"], slot["ends_at"], other_slot["starts_at"], other_slot["ends_at"]
        ):
            raise ApiError(
                "ERR_GUIDE_SCHEDULE_CONFLICT",
                "The guide already holds an overlapping duty.",
            )
        if other_slot["starts_at"].date() == day:
            day_hours += calc.dec(other_slot["duration_hours"])
    if day_hours + calc.dec(slot["duration_hours"]) > calc.GUIDE_DAILY_HOURS_CEILING:
        raise ApiError(
            "ERR_GUIDE_SCHEDULE_CONFLICT",
            "The guide would exceed the 10.0 hour daily ceiling.",
        )

    required_cert = calc.ACTIVITY_CERTIFICATION[slot["activity_type"]]
    if (
        staff["employment_status"] != "ACTIVE"
        or staff["season_id"] != slot["season_id"]
        or required_cert not in (staff.get("certifications") or [])
    ):
        raise ApiError(
            "ERR_CERTIFICATION_MISSING",
            "The guide must be ACTIVE in this season and hold %s." % required_cert,
        )

    row = db.insert(
        "guide_assignments",
        {
            "slot_id": slot["id"],
            "staff_member_id": staff["id"],
            "guide_role": guide_role,
            "assignment_status": "SCHEDULED",
            "credited_hours": 0,
        },
    )
    touch = Touch()
    touch.slot(slot)
    touch.finalize()
    return created(assignment_json(row))


@bp.get("/guide-assignments/<assignment_id>")
def read_assignment(assignment_id):
    auth(*ASSIGNMENT_READERS)
    return ok(assignment_json(find("guide_assignments", assignment_id)))


@bp.get("/guide-assignments")
def list_assignments():
    auth(*ASSIGNMENT_READERS)
    rows = derive.rows_of(
        "guide_assignments",
        slot_id=fields.query_filter("slot_id"),
        staff_member_id=fields.query_filter("staff_member_id"),
        assignment_status=fields.query_enum("assignment_status", ASSIGNMENT_STATUSES),
    )
    return listing(rows, assignment_json)


@bp.post("/guide-assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    auth("RanchManager")
    assignment = find("guide_assignments", assignment_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    slot = db.activity_slots.get(assignment["slot_id"])
    if slot is None or slot["slot_status"] not in ("DRAFT", "OPEN", "HOLD"):
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "A guide cannot be released from a slot that has started or finished.",
        )
    if assignment["assignment_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "Only a SCHEDULED assignment may be released.",
        )

    assignment["assignment_status"] = "RELEASED"
    touch = Touch()
    touch.add(assignment)
    touch.slot(slot)
    touch.finalize()
    return ok(assignment_json(assignment))
