"""Playback slots: window fit, first come, series priority (PRD 3.4 / 3.5)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition, not_found

bp = Blueprint("slots", __name__)

READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_CONTENT_REVIEWER,
    C.ROLE_PRODUCER,
)


def _conflict():
    return ApiError("ERR_SLOT_WINDOW_CONFLICT", "The requested airtime conflicts with a booked slot")


@bp.post("/playback-slots")
def create_slot():
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    channel_id = validation.req_id(body, "channel_id")
    program_id = validation.req_id(body, "program_id")
    start_at = validation.req_datetime(body, "start_at")
    series_id = validation.opt_id(body, "series_id")
    # priority 5: channel_id, program_id, then series_id
    channel = db.get("channels", channel_id)
    if channel is None:
        raise not_found("channel", channel_id)
    program = db.get("programs", program_id)
    if program is None:
        raise not_found("program", program_id)
    series = None
    if series_id is not None:
        series = db.get("series", series_id)
        if series is None:
            raise not_found("series", series_id)
    # priority 11
    if program["review_status"] != "APPROVED":
        raise ApiError("ERR_PROGRAM_NOT_APPROVED", "The program is not approved for scheduling")
    # priority 12
    if program["clearance_status"] != "CLEARED":
        raise ApiError("ERR_ATTESTATION_INCOMPLETE", "The program's attestations are incomplete")
    # priority 13
    if series is not None and series["status"] != "ACTIVE":
        raise ApiError("ERR_SERIES_NOT_ACTIVE", "The named series is not active")

    occupied_seconds = program["runtime_seconds"] + channel["inter_program_buffer_seconds"]
    end_at = calc.slot_end_at(start_at, occupied_seconds)
    # priority 26
    if not calc.window_fit(channel, start_at, occupied_seconds):
        raise ApiError(
            "ERR_SLOT_OUTSIDE_CHANNEL_WINDOW", "The slot footprint falls outside the channel window"
        )

    overlaps = [
        slot
        for slot in db.all_rows("playback_slots")
        if slot["channel_id"] == channel_id
        and slot["status"] == "SCHEDULED"
        and calc.intervals_overlap(start_at, end_at, slot["start_at"], slot["end_at"])
    ]

    preempt_targets = []
    if overlaps:
        # PRD 3.4: only a series-priority challenger can proceed, in this order.
        if series is None:
            raise _conflict()
        if not channel["preemption_enabled"]:
            raise _conflict()
        if series["status"] != "ACTIVE":
            raise ApiError("ERR_SERIES_NOT_ACTIVE", "The named series is not active")
        if series["remaining_hold_slots"] < 1:
            raise ApiError("ERR_SERIES_HOLD_EXHAUSTED", "The series has no remaining hold slots")
        for incumbent in overlaps:
            if not _displaceable(series, incumbent):
                raise _conflict()
            preempt_targets.append(incumbent)
    elif series is not None and series["remaining_hold_slots"] < 1:
        # priority 28 still applies to a hold booking in free airtime
        raise ApiError("ERR_SERIES_HOLD_EXHAUSTED", "The series has no remaining hold slots")

    # priority 34
    if series is not None and series["producer_id"] != program["producer_id"]:
        raise ApiError(
            "ERR_SERIES_NOT_OWNED_BY_PRODUCER", "The series belongs to a different producer"
        )
    # priority 35
    producer = db.get("producers", program["producer_id"])
    if (
        producer is not None
        and calc.certification_level(producer) == "BASIC"
        and channel["tier"] in ("EDUCATIONAL", "GOVERNMENT")
    ):
        raise ApiError(
            "ERR_CHANNEL_TIER_NOT_ELIGIBLE",
            "A BASIC-certified producer may occupy only a PUBLIC channel",
        )

    sequence_number = channel["slot_sequence_high"] + 1
    channel["slot_sequence_high"] = sequence_number
    row = db.new_row(
        "playback_slots",
        {
            "channel_id": channel_id,
            "program_id": program_id,
            "series_id": series_id,
            "booking_type": "SERIES_HOLD" if series is not None else "FIRST_COME",
            "start_at": start_at,
            "occupied_seconds": occupied_seconds,
            "end_at": end_at,
            "status": "SCHEDULED",
            "required_crew_roles": list(program["required_crew_roles"]),
            "preempted_by_slot_id": None,
            "measured_households": None,
            "aired_at": None,
            "sequence_number": sequence_number,
            "cancellation_reason": None,
        },
    )
    db.bump(channel)
    if series is not None:
        series["remaining_hold_slots"] = series["remaining_hold_slots"] - 1
        db.bump(series)
    for incumbent in preempt_targets:
        cascades.preempt_slot(incumbent, row["id"])
    return support.created("playback_slots", row)


def _displaceable(challenger_series, incumbent):
    """An incumbent is displaceable only on the strictly-earlier seniority test."""
    if incumbent["booking_type"] != "FIRST_COME":
        return False
    incumbent_series = None
    if incumbent.get("series_id"):
        incumbent_series = db.get("series", incumbent["series_id"])
    if incumbent_series is not None:
        key = incumbent_series["seniority_at"] or incumbent["created_at"]
    else:
        key = incumbent["created_at"]
    challenger_key = challenger_series["seniority_at"]
    if challenger_key is None:
        return False
    challenger_key = challenger_key.replace(microsecond=0)
    key = key.replace(microsecond=0)
    if challenger_key < key:
        return True
    if challenger_key == key and incumbent_series is not None:
        return challenger_series["sequence_number"] < incumbent_series["sequence_number"]
    return False


@bp.get("/playback-slots/<slot_id>")
def read_slot(slot_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("playback_slots", slot_id)
    return support.single("playback_slots", row)


@bp.get("/playback-slots")
def list_slots():
    middleware.authorize(*READ_ROLES)
    channel_id = validation.query_string("channel_id")
    program_id = validation.query_string("program_id")
    series_id = validation.query_string("series_id")
    preempted_by_slot_id = validation.query_string("preempted_by_slot_id")
    status = validation.query_enum("status", C.SLOT_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "playback_slots",
        [
            ("channel_id", channel_id),
            ("program_id", program_id),
            ("series_id", series_id),
            ("preempted_by_slot_id", preempted_by_slot_id),
            ("status", status),
        ],
    )
    return support.collection_response("playback_slots", rows)


@bp.post("/playback-slots/<slot_id>/air")
def air_slot(slot_id):
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    measured_households = validation.req_int(body, "measured_households", minimum=0)
    slot = support.must_exist("playback_slots", slot_id)
    if slot["status"] != "SCHEDULED":
        raise invalid_transition("Only a scheduled slot may air")
    program = db.get("programs", slot["program_id"])
    # priority 11
    if program is None or program["review_status"] != "APPROVED":
        raise ApiError("ERR_PROGRAM_NOT_APPROVED", "The program is no longer approved")
    # priority 19
    if calc.staffing_status(slot) == "UNDERSTAFFED":
        raise ApiError("ERR_SLOT_UNDERSTAFFED", "The slot is understaffed")
    # priority 31
    if db.now() < slot["start_at"]:
        raise ApiError("ERR_AIRTIME_NOT_REACHED", "The slot's airtime has not been reached")

    instant = db.now()
    slot["status"] = "AIRED"
    slot["aired_at"] = instant
    slot["measured_households"] = measured_households
    db.bump(slot)

    credit = calc.credited_hours_tenths(slot)
    volunteer_tenths = 0
    for assignment in db.all_rows("crew_assignments"):
        if assignment["slot_id"] != slot["id"] or assignment["status"] != "CONFIRMED":
            continue
        assignment["status"] = "COMPLETED"
        assignment["credited_hours_tenths"] = credit
        db.bump(assignment)
    for assignment in db.all_rows("crew_assignments"):
        if assignment["slot_id"] == slot["id"] and assignment["status"] == "COMPLETED":
            volunteer_tenths += assignment["credited_hours_tenths"]

    index = calc.community_impact_index(measured_households, 0, volunteer_tenths, "PROVISIONAL")
    db.new_row(
        "archive_assets",
        {
            "program_id": slot["program_id"],
            "source_slot_id": slot["id"],
            "retention_class": None,
            "retain_until": None,
            "on_demand_status": "PENDING",
            "on_demand_views": 0,
            "measured_households": measured_households,
            "volunteer_hours_tenths": volunteer_tenths,
            "community_impact_index": index,
            "impact_variant": "PROVISIONAL",
            "published_at": None,
            "purged_at": None,
        },
    )
    return support.single("playback_slots", slot)


@bp.post("/playback-slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    cancellation_reason = validation.req_string(body, "cancellation_reason")
    slot = support.must_exist("playback_slots", slot_id)
    if slot["status"] != "SCHEDULED":
        raise invalid_transition("Only a scheduled slot may be cancelled")
    slot["status"] = "CANCELLED"
    slot["cancellation_reason"] = cancellation_reason
    db.bump(slot)
    cascades.restore_hold_slot(slot, count_missed_window=True)
    cascades.release_slot_crew(slot, "SLOT_CANCELLED")
    return support.single("playback_slots", slot)
