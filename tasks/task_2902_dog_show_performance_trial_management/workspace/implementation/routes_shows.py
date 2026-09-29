"""Show applications, sanctioning, show day and weather."""
from flask import Blueprint

import agg
from auth import authenticate, must_get, owner_check
import calc
from common import ALL_ROLES, POINTS_SCALES, SHOW_STATUSES, SHOW_TYPES, date_midnight
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("shows", __name__)


def _new_show_fields(**inputs):
    fields = dict(inputs)
    fields.update({
        "status": "DRAFT",
        "submitted_at": None,
        "approval_decided_at": None,
        "approved_by_user_id": None,
        "return_reason": None,
        "revision_count": 0,
        "armband_high_water": 0,
        "confirmed_entry_count": 0,
        "fee_charged_cents": 0,
        "fee_refunded_cents": 0,
        "fee_retained_cents": 0,
        "fee_collected_cents": 0,
        "fee_assessment_delta_cents": 0,
        "levy_total_cents": 0,
        "points_awarded_total": 0,
        "temperature_reading_count": 0,
        "current_heat_index_c": None,
        "current_advisory_level": None,
    })
    return fields


@bp.post("/shows")
def create_show():
    user_id, _role = authenticate(["ClubOfficer"])
    body = shape.json_body()
    club_id = shape.string_field(body, "club_id")
    show_name = shape.string_field(body, "show_name")
    show_date = shape.date_field(body, "show_date")
    show_type = shape.string_field(body, "show_type", enum=SHOW_TYPES)
    venue_name = shape.string_field(body, "venue_name")
    outdoor_venue = shape.bool_field(body, "outdoor_venue")
    entry_open_at = shape.instant_field(body, "entry_open_at")
    entry_close_at = shape.instant_field(body, "entry_close_at")
    max_total_entries = shape.int_field(body, "max_total_entries", minimum=1)
    scale = shape.string_field(
        body, "championship_points_scale", enum=POINTS_SCALES
    )
    club = must_get("clubs", club_id)
    owner_check(user_id, club_id)
    if club["sanction_status"] != "ACTIVE":
        fail("ERR_CLUB_NOT_ACTIVE", "The hosting club is not ACTIVE.")
    rec = store.insert("shows", _new_show_fields(
        club_id=club_id,
        show_name=show_name,
        show_date=show_date,
        show_type=show_type,
        venue_name=venue_name,
        outdoor_venue=outdoor_venue,
        entry_open_at=entry_open_at,
        entry_close_at=entry_close_at,
        max_total_entries=max_total_entries,
        championship_points_scale=scale,
    ))
    return object_response(store.serialize(rec), 201)


@bp.get("/shows/<show_id>")
def read_show(show_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("shows", show_id)))


@bp.get("/shows")
def list_shows():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("shows"), {
        "club_id": "club_id",
        "status": "status",
        "show_date": "show_date",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/shows/<show_id>/submit")
def submit_show(show_id):
    user_id, _role = authenticate(["ClubOfficer"])
    show = must_get("shows", show_id)
    shape.json_body()
    owner_check(user_id, show["club_id"])
    if show["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_SHOW_NOT_IN_DRAFT",
             "A show in %s may not be submitted." % show["status"])
    club = store.get("clubs", show["club_id"])
    if club["sanction_status"] != "ACTIVE":
        fail("ERR_CLUB_NOT_ACTIVE", "The hosting club is not ACTIVE.")
    if club["events_approved_count"] >= club["annual_event_allowance"]:
        fail("ERR_CLUB_ALLOWANCE_EXHAUSTED",
             "The club's annual event allowance is spent.")
    if show["status"] == "DRAFT":
        if not show["entry_open_at"] < show["entry_close_at"]:
            fail("ERR_INVALID_REQUEST",
                 "entry_open_at must be strictly earlier than entry_close_at.")
        if not show["entry_close_at"] < date_midnight(show["show_date"]):
            fail("ERR_INVALID_REQUEST",
                 "entry_close_at must be strictly earlier than the show date.")
    changes = {"status": "SUBMITTED", "submitted_at": store.now()}
    if show["status"] == "RETURNED":
        changes["return_reason"] = None
    set_fields(show, **changes)
    store.touch(show)
    return object_response(store.serialize(show))


@bp.post("/shows/<show_id>/approve")
def approve_show(show_id):
    user_id, _role = authenticate(["SanctionOfficer"])
    show = must_get("shows", show_id)
    shape.json_body()
    if show["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "A show in %s may not be approved." % show["status"])
    club = store.get("clubs", show["club_id"])
    if club["sanction_status"] != "ACTIVE":
        fail("ERR_CLUB_NOT_ACTIVE", "The hosting club is not ACTIVE.")
    if club["events_approved_count"] >= club["annual_event_allowance"]:
        fail("ERR_CLUB_ALLOWANCE_EXHAUSTED",
             "The club's annual event allowance is spent.")
    set_fields(
        show,
        status="APPROVED",
        approved_by_user_id=user_id,
        approval_decided_at=store.now(),
    )
    store.touch(show)
    agg.recompute_club_events(club)
    return object_response(store.serialize(show))


@bp.post("/shows/<show_id>/return")
def return_show(show_id):
    authenticate(["SanctionOfficer"])
    show = must_get("shows", show_id)
    body = shape.json_body()
    return_reason = shape.string_field(body, "return_reason")
    if show["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "A show in %s may not be returned." % show["status"])
    set_fields(
        show,
        status="RETURNED",
        return_reason=return_reason,
        approval_decided_at=store.now(),
        revision_count=show["revision_count"] + 1,
    )
    store.touch(show)
    return object_response(store.serialize(show))


@bp.post("/shows/<show_id>/open-day")
def open_show_day(show_id):
    authenticate(["ShowSecretary"])
    show = must_get("shows", show_id)
    shape.json_body()
    if show["status"] != "APPROVED":
        fail("ERR_INVALID_STATE",
             "A show in %s may not open the day." % show["status"])
    classes = agg.classes_of_show(show_id)
    if not classes:
        fail("ERR_INVALID_STATE", "The show has no classes.")
    for cls in classes:
        if cls["status"] not in ("CLOSED", "SCHEDULED"):
            fail("ERR_INVALID_STATE",
                 "Class %s has not closed its entries." % cls["class_code"])
    set_fields(show, status="IN_PROGRESS")
    store.touch(show)
    return object_response(store.serialize(show))


@bp.post("/shows/<show_id>/close")
def close_show(show_id):
    authenticate(["ShowSecretary"])
    show = must_get("shows", show_id)
    shape.json_body()
    if show["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE",
             "A show in %s may not be closed." % show["status"])
    for cls in agg.classes_of_show(show_id):
        if cls["status"] not in ("COMPLETED", "ABANDONED"):
            fail("ERR_CLASSES_NOT_COMPLETE",
                 "Class %s has not been judged." % cls["class_code"])
    set_fields(show, status="COMPLETED")
    store.touch(show)
    return object_response(store.serialize(show))


@bp.post("/shows/<show_id>/temperature-readings")
def record_temperature(show_id):
    authenticate(["ShowSecretary"])
    show = must_get("shows", show_id)
    body = shape.json_body()
    recorded_temp_c = shape.number_field(body, "recorded_temp_c")
    humidity = shape.number_field(body, "relative_humidity_pct")
    if show["status"] not in ("APPROVED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE",
             "A reading may not be taken while the show is %s." % show["status"])
    index, level = calc.heat_evaluation(recorded_temp_c, humidity)
    set_fields(
        show,
        current_heat_index_c=index,
        current_advisory_level=level,
        temperature_reading_count=show["temperature_reading_count"] + 1,
    )
    store.touch(show)
    if show["status"] == "IN_PROGRESS":
        if level == "RED" and show["outdoor_venue"]:
            for entry in agg.entries_of_show(show_id):
                cls = store.get("classes", entry["class_id"])
                if cls["class_level"] == "PERFORMANCE" and entry["welfare_status"] == "CLEAR":
                    set_fields(entry, welfare_status="HEAT_HOLD")
        if level != "RED" or not show["outdoor_venue"]:
            for entry in agg.entries_of_show(show_id):
                if entry["welfare_status"] == "HEAT_HOLD":
                    set_fields(entry, welfare_status="CLEAR")
    return object_response(store.serialize(show))
