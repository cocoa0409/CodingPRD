"""Clubs, judges, handlers, dogs and the logical clock."""
from flask import Blueprint

from auth import authenticate, must_get, owner_check
from common import (
    ALL_ROLES, CARD_TYPES, CLUB_SANCTION_STATUS, DISCIPLINES, GROUP_CODES,
    HANDLER_STATUS, JUDGE_STATUS, MEASUREMENT_STATUSES, REGION_CODES, SEXES,
    canonical_instant, one_dp,
)
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("core", __name__)


def _unique(collection, field, value):
    for rec in store.rows(collection):
        if rec[field] == value:
            fail("ERR_INVALID_REQUEST",
                 "%s '%s' is already registered." % (field, value))


def _valid_club_code(code):
    if not (3 <= len(code) <= 8):
        return False
    for char in code:
        if not (char.isdigit() or (char.isalpha() and char == char.upper() and char.isascii())):
            return False
    return True


# ------------------------------------------------------------------- clubs
@bp.post("/clubs")
def create_club():
    authenticate(["SanctionOfficer"])
    body = shape.json_body()
    name = shape.string_field(body, "name")
    club_code = shape.string_field(body, "club_code")
    region_code = shape.string_field(body, "region_code", enum=REGION_CODES)
    sanction_status = shape.string_field(
        body, "sanction_status", required=False, default="ACTIVE",
        enum=CLUB_SANCTION_STATUS,
    )
    allowance = shape.int_field(
        body, "annual_event_allowance", required=False, default=2, minimum=0
    )
    sanction_note = shape.string_field(
        body, "sanction_note", required=False, default=None, allow_blank=True
    )
    if not _valid_club_code(club_code):
        fail("ERR_INVALID_REQUEST",
             "club_code must be three to eight uppercase alphanumerics.")
    _unique("clubs", "club_code", club_code)
    rec = store.insert("clubs", {
        "name": name,
        "club_code": club_code,
        "region_code": region_code,
        "sanction_status": sanction_status,
        "annual_event_allowance": allowance,
        "events_approved_count": 0,
        "sanction_note": sanction_note,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/clubs/<club_id>")
def read_club(club_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("clubs", club_id)))


# ------------------------------------------------------------------- judges
@bp.post("/judges")
def create_judge():
    authenticate(["SanctionOfficer"])
    body = shape.json_body()
    judge_number = shape.string_field(body, "judge_number")
    full_name = shape.string_field(body, "full_name")
    groups = shape.str_list_field(
        body, "approved_breed_group_codes", enum=GROUP_CODES
    )
    disciplines = shape.str_list_field(
        body, "approved_performance_disciplines", enum=DISCIPLINES
    )
    home_region_code = shape.string_field(
        body, "home_region_code", enum=REGION_CODES
    )
    max_daily = shape.int_field(
        body, "max_daily_dog_count", required=False, default=175, minimum=1
    )
    status = shape.string_field(
        body, "status", required=False, default="ACTIVE", enum=JUDGE_STATUS
    )
    _unique("judges", "judge_number", judge_number)
    rec = store.insert("judges", {
        "judge_number": judge_number,
        "full_name": full_name,
        "approved_breed_group_codes": groups,
        "approved_performance_disciplines": disciplines,
        "home_region_code": home_region_code,
        "max_daily_dog_count": max_daily,
        "status": status,
        "confirmed_slot_count": 0,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/judges/<judge_id>")
def read_judge(judge_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("judges", judge_id)))


# ----------------------------------------------------------------- handlers
@bp.post("/handlers")
def create_handler():
    authenticate(["SanctionOfficer", "ShowSecretary"])
    body = shape.json_body()
    handler_name = shape.string_field(body, "handler_name")
    member_number = shape.string_field(body, "member_number")
    region_code = shape.string_field(body, "region_code", enum=REGION_CODES)
    status = shape.string_field(
        body, "status", required=False, default="ACTIVE", enum=HANDLER_STATUS
    )
    suspension_reason = shape.string_field(
        body, "suspension_reason", required=False, default=None, allow_blank=True
    )
    _unique("handlers", "member_number", member_number)
    rec = store.insert("handlers", {
        "handler_name": handler_name,
        "member_number": member_number,
        "region_code": region_code,
        "status": status,
        "suspension_reason": suspension_reason,
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/handlers/<handler_id>")
def read_handler(handler_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("handlers", handler_id)))


# --------------------------------------------------------------------- dogs
@bp.post("/dogs")
def create_dog():
    user_id, _role = authenticate(["Handler"])
    body = shape.json_body()
    registration_number = shape.string_field(body, "registration_number")
    call_name = shape.string_field(body, "call_name")
    breed_code = shape.string_field(body, "breed_code")
    group_code = shape.string_field(body, "group_code", enum=GROUP_CODES)
    sex = shape.string_field(body, "sex", enum=SEXES)
    birth_date = shape.date_field(body, "birth_date")
    owner_handler_id = shape.string_field(body, "owner_handler_id")
    _unique("dogs", "registration_number", registration_number)
    must_get("handlers", owner_handler_id)
    owner_check(user_id, owner_handler_id)
    rec = store.insert("dogs", {
        "registration_number": registration_number,
        "call_name": call_name,
        "breed_code": breed_code,
        "group_code": group_code,
        "sex": sex,
        "birth_date": birth_date,
        "owner_handler_id": owner_handler_id,
        "measured_height_cm": None,
        "measurement_status": "UNMEASURED",
        "championship_points_total": 0,
        "majors_count": 0,
        "qualifying_leg_counts": {"AGILITY": 0, "OBEDIENCE": 0, "RALLY": 0},
        "title_codes": [],
    })
    return object_response(store.serialize(rec), 201)


@bp.get("/dogs/<dog_id>")
def read_dog(dog_id):
    authenticate(ALL_ROLES)
    return object_response(store.serialize(must_get("dogs", dog_id)))


@bp.get("/dogs")
def list_dogs():
    authenticate(ALL_ROLES)
    limit, offset = shape.pagination()
    rows = shape.apply_filters(store.rows("dogs"), {
        "owner_handler_id": "owner_handler_id",
        "breed_code": "breed_code",
        "measurement_status": "measurement_status",
    })
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/dogs/<dog_id>/measurement")
def record_measurement(dog_id):
    authenticate(["Judge"])
    dog = must_get("dogs", dog_id)
    body = shape.json_body()
    measured = shape.number_field(body, "measured_height_cm")
    card_type = shape.string_field(body, "card_type", enum=CARD_TYPES)
    if dog["measurement_status"] == "PERMANENT_CARD":
        fail("ERR_MEASUREMENT_LOCKED",
             "A dog holding a permanent measuring card may not be re-measured.")
    set_fields(dog, measured_height_cm=one_dp(measured),
               measurement_status=card_type)
    return object_response(store.serialize(dog))


# -------------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    body = shape.json_body()
    to_iso8601 = shape.string_field(body, "to_iso8601")
    canonical = canonical_instant(to_iso8601)
    if canonical is None:
        fail("ERR_INVALID_REQUEST",
             "to_iso8601 must be an ISO-8601 UTC instant.")
    store.set_clock(canonical)
    return object_response({})
