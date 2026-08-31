from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_part, fail,
    req_string, req_enum, req_int, opt_id, clock_iso,
    ALL_ROLES, ROLE_ADMIN, PART_CLASSES,
)

bp = Blueprint("parts", __name__)


@bp.route(API_PREFIX + "/parts", methods=["POST"])
def create_part():
    authenticate([ROLE_ADMIN])
    body = json_body()
    part_number = req_string(body, "part_number")
    description_text = req_string(body, "description_text")
    part_class = req_enum(body, "part_class", PART_CLASSES)
    unit_price_cents = req_int(body, "unit_price_cents", 1)
    lead_time_days = req_int(body, "lead_time_days", 0)

    part = new_entity({
        "part_number": part_number,
        "description_text": description_text,
        "part_class": part_class,
        "unit_price_cents": unit_price_cents,
        "lead_time_days": lead_time_days,
        "lifecycle_state": "ACTIVE",
        "superseded_by_part_id": None,
        "obsoleted_at": None,
    })
    db.parts[part["id"]] = part
    return object_response(serialize(part), 201)


@bp.route(API_PREFIX + "/parts/<part_id>", methods=["GET"])
def read_part(part_id):
    authenticate(ALL_ROLES)
    part = get_part(part_id)
    return object_response(serialize(part))


@bp.route(API_PREFIX + "/parts", methods=["GET"])
def list_parts():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.parts)
    rows = filter_equals(rows, "superseded_by_part_id")
    rows = filter_equals(rows, "lifecycle_state")
    rows = filter_equals(rows, "part_class")
    return paginate(rows)


@bp.route(API_PREFIX + "/parts/<part_id>/obsolete", methods=["POST"])
def obsolete_part(part_id):
    authenticate([ROLE_ADMIN])
    part = get_part(part_id)
    body = json_body()
    replacement_id = opt_id(body, "replacement_part_id")
    replacement = None
    if replacement_id is not None:
        replacement = get_part(replacement_id)
        if replacement["id"] == part["id"]:
            fail("ERR_VALIDATION", "replacement_part_id must not be the part itself.")
        if replacement["lifecycle_state"] == "DISCONTINUED":
            fail("ERR_VALIDATION", "replacement_part_id must not be a DISCONTINUED part.")

    if replacement is not None:
        if part["lifecycle_state"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION")
        part["lifecycle_state"] = "OBSOLETE"
        part["superseded_by_part_id"] = replacement["id"]
        part["obsoleted_at"] = clock_iso()
    else:
        if part["lifecycle_state"] not in ("ACTIVE", "OBSOLETE"):
            fail("ERR_INVALID_STATE_TRANSITION")
        part["lifecycle_state"] = "DISCONTINUED"
        part["superseded_by_part_id"] = None
        part["obsoleted_at"] = clock_iso()

    touch(part)
    return object_response(serialize(part))
