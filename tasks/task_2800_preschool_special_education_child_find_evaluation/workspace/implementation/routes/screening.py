"""Screening events and slots (PRD section 3.2)."""
from datetime import timedelta

from flask import Blueprint

from db import base_row, db, now_utc, touch
from errors import ApiError
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import calc, derive, rules
from validation import (
    ATTENDANCE,
    EVENT_STATUS,
    SCREENING_RESULT,
    SLOT_STATUS,
    bad,
    body,
    opt_enum,
    opt_lang,
    opt_lang_list,
    opt_int,
    present,
    q_enum,
    q_str,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("screening", __name__)

EVENT_READ_ROLES = ("ChildFindCoordinator", "PlacementAdministrator", "DistrictAdmin")
SLOT_READ_ROLES = (
    "ChildFindCoordinator",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)

EVENT_TRANSITIONS = {
    ("SCHEDULED", "OPEN"),
    ("OPEN", "CLOSED"),
    ("CLOSED", "COMPLETED"),
    ("SCHEDULED", "CANCELLED"),
    ("OPEN", "CANCELLED"),
    ("CLOSED", "CANCELLED"),
}


@bp.post("/screening-events")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def create_event():
    data = body()
    site_id = req_id(data, "site_id")
    event_label = req_str(data, "event_label")
    window_start = req_datetime(data, "window_start_utc")
    window_end = req_datetime(data, "window_end_utc")
    slot_capacity = req_int(data, "slot_capacity", minimum=1)
    slot_length = opt_int(data, "slot_length_minutes", 20, minimum=10, maximum=60, multiple_of=5)
    interpreter_languages = opt_lang_list(data, "interpreter_languages", [])
    if window_end <= window_start:
        bad("Field 'window_end_utc' must be strictly after 'window_start_utc'")

    site = rules.fetch("community_sites", site_id)

    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_NOT_ELIGIBLE", "Host site status is not ACTIVE")
    if not site["screening_host_approved"]:
        raise ApiError(
            "ERR_SITE_NOT_ELIGIBLE", "Host site is not approved to host screening events"
        )
    if rules.site_event_overlap(site_id, window_start, window_end):
        raise ApiError(
            "ERR_SITE_EVENT_OVERLAP", "Window overlaps another event at this site"
        )

    row = base_row()
    row.update(
        {
            "site_id": site_id,
            "event_label": event_label,
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "slot_length_minutes": slot_length,
            "slot_capacity": slot_capacity,
            "interpreter_languages": interpreter_languages,
            "status": "SCHEDULED",
        }
    )
    db.screening_events[row["id"]] = row
    return object_response(derive.event_out(row), 201)


@bp.post("/screening-events/<event_id>/status")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def set_event_status(event_id):
    data = body()
    target = req_enum(data, "target_status", EVENT_STATUS)
    event = rules.fetch("screening_events", event_id)

    if (event["status"], target) not in EVENT_TRANSITIONS:
        raise ApiError(
            "ERR_INVALID_EVENT_STATE",
            "Event cannot move from %s to %s" % (event["status"], target),
        )

    if target == "OPEN":
        site = db.community_sites.get(event["site_id"])
        if site is None or site["status"] != "ACTIVE":
            raise ApiError("ERR_SITE_NOT_ELIGIBLE", "Host site status is not ACTIVE")
        if not site["screening_host_approved"]:
            raise ApiError(
                "ERR_SITE_NOT_ELIGIBLE", "Host site is not approved to host screening events"
            )
        if now_utc() >= event["window_end_utc"]:
            raise ApiError(
                "ERR_INVALID_EVENT_STATE", "Event window has already closed on the logical clock"
            )

    if target == "COMPLETED":
        if any(s["status"] == "BOOKED" for s in derive.slots_of_event(event_id)):
            raise ApiError(
                "ERR_SCREENING_SLOTS_UNRESOLVED",
                "Every appointment must be ATTENDED, NO_SHOW or CANCELLED first",
            )

    event["status"] = target
    touch(event)

    if target == "CANCELLED":
        for slot in derive.slots_of_event(event_id):
            if slot["status"] == "BOOKED":
                slot["status"] = "CANCELLED"
                touch(slot)

    return object_response(derive.event_out(event))


@bp.post("/screening-events/<event_id>/slots")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def book_slot(event_id):
    data = body()
    child_id = req_id(data, "child_id")
    slot_start = req_datetime(data, "slot_start_utc")
    expected_version = req_int(data, "expected_screening_event_version")
    requested_language = opt_lang(data, "requested_language_code", "en")

    event = rules.fetch("screening_events", event_id)
    child = rules.fetch("children", child_id)

    if expected_version != event["version"]:
        raise ApiError(
            "ERR_STALE_SCREENING_EVENT_VERSION",
            "Screening event version has advanced since it was read",
        )
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_EVENT_STATE", "Only an OPEN event accepts bookings")
    if requested_language != "en" and requested_language not in event["interpreter_languages"]:
        raise ApiError(
            "ERR_INTERPRETER_NOT_PROVIDED",
            "Event has no interpreter coverage for '%s'" % requested_language,
        )

    slot_end = slot_start + timedelta(minutes=event["slot_length_minutes"])
    if slot_start < event["window_start_utc"] or slot_end > event["window_end_utc"]:
        raise ApiError(
            "ERR_SLOT_OUTSIDE_EVENT_WINDOW",
            "Appointment must fall entirely inside the event window",
        )

    effective = calc.effective_slot_capacity(
        event["slot_capacity"],
        event["slot_length_minutes"],
        event["window_start_utc"],
        event["window_end_utc"],
    )
    if derive.event_booked_count(event_id) >= effective:
        raise ApiError(
            "ERR_SCREENING_CAPACITY_EXCEEDED", "Screening event has no remaining capacity"
        )

    row = base_row()
    row.update(
        {
            "screening_event_id": event_id,
            "child_id": child["id"],
            "slot_start_utc": slot_start,
            "slot_end_utc": slot_end,
            "requested_language_code": requested_language,
            "status": "BOOKED",
            "screening_result": None,
        }
    )
    db.screening_slots[row["id"]] = row
    touch(event)
    return object_response(derive.slot_out(row), 201)


@bp.post("/screening-slots/<slot_id>/outcome")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def slot_outcome(slot_id):
    data = body()
    attendance = req_enum(data, "attendance", ATTENDANCE)
    screening_result = opt_enum(data, "screening_result", SCREENING_RESULT)
    if attendance == "ATTENDED" and screening_result is None:
        bad("Field 'screening_result' is required when attendance is ATTENDED")

    slot = rules.fetch("screening_slots", slot_id)
    if slot["status"] != "BOOKED":
        raise ApiError(
            "ERR_INVALID_SLOT_STATE", "Only a BOOKED appointment can take an outcome"
        )

    event = db.screening_events.get(slot["screening_event_id"])
    if attendance in ("ATTENDED", "NO_SHOW"):
        if event is None or event["status"] not in ("OPEN", "CLOSED"):
            raise ApiError(
                "ERR_INVALID_EVENT_STATE",
                "Parent event must be OPEN or CLOSED to record attendance",
            )

    slot["status"] = attendance
    if attendance == "ATTENDED":
        slot["screening_result"] = screening_result
    touch(slot)

    if attendance == "ATTENDED" and screening_result == "REFER":
        child = db.children.get(slot["child_id"])
        if child is not None:
            referral = rules.create_referral(child, "SCREENING", None, slot["id"])
            if referral["eligibility_pathway"] == "AGE_INELIGIBLE":
                referral["intake_status"] = "DECLINED"
                touch(referral)

    return object_response(derive.slot_out(slot))


@bp.get("/screening-events/<event_id>")
@endpoint(*EVENT_READ_ROLES)
def get_event(event_id):
    return object_response(derive.event_out(rules.fetch("screening_events", event_id)))


@bp.get("/screening-events")
@endpoint(*EVENT_READ_ROLES)
def list_events():
    site_id = q_str("site_id")
    status = q_enum("status", EVENT_STATUS)
    rows = [
        r
        for r in db.screening_events.values()
        if matches(r, "site_id", site_id) and matches(r, "status", status)
    ]
    return paged(rows, derive.event_out)


@bp.get("/screening-slots/<slot_id>")
@endpoint(*SLOT_READ_ROLES)
def get_slot(slot_id):
    return object_response(derive.slot_out(rules.fetch("screening_slots", slot_id)))


@bp.get("/screening-slots")
@endpoint(*SLOT_READ_ROLES)
def list_slots():
    event_id = q_str("screening_event_id")
    child_id = q_str("child_id")
    result = q_enum("screening_result", SCREENING_RESULT)
    status = q_enum("status", SLOT_STATUS)
    rows = [
        r
        for r in db.screening_slots.values()
        if matches(r, "screening_event_id", event_id)
        and matches(r, "child_id", child_id)
        and matches(r, "screening_result", result)
        and matches(r, "status", status)
    ]
    return paged(rows, derive.slot_out)
