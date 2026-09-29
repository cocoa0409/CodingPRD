"""The logical clock, the treatment menu, the room inventory, the therapist
roster and shift blocks (PRD §2.4, §3.1, §3.2).
"""

from flask import Blueprint

import auth
import domain
import envelope
import errors
import store
import validation as v
from errors import ApiError
from store import db, touch

bp = Blueprint("catalog", __name__)

ROOM_CLASSES = ("DRY", "WET", "HYDRO", "COUPLES")
ROOM_STATUSES = ("ACTIVE", "MAINTENANCE", "OUT_OF_SERVICE")
SCOPE_LEVELS = ("BASIC", "ADVANCED")
EMPLOYMENT_TYPES = ("EMPLOYEE", "CONTRACTOR")
COMMISSION_TIERS = ("JUNIOR", "SENIOR", "MASTER")
BLOCK_TYPES = ("AVAILABLE", "BREAK", "ADMIN")

CODE_PATTERN = r"^[A-Z0-9\-]{1,24}$"
STATE_PATTERN = r"^[A-Z]{2}$"


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.authenticate(auth.SPA_DIRECTOR, auth.COMPLIANCE_OFFICER, auth.SPA_COORDINATOR)
    body = v.json_body()
    instant = v.field_instant(body, "current_utc")
    if instant < db.clock:
        raise ApiError(errors.ERR_CLOCK_REWIND,
                       "The logical clock never rewinds.")
    db.clock = instant
    return envelope.ok({"current_utc": envelope.iso3(instant)})


# --------------------------------------------------------------------------
# treatment types
# --------------------------------------------------------------------------

@bp.route("/treatment-types", methods=["POST"])
def create_treatment_type():
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    code = v.field_str(body, "code", max_len=24, pattern=CODE_PATTERN)
    name = v.field_str(body, "name", max_len=200)
    duration = v.field_int(body, "duration_minutes", minimum=15, maximum=240,
                           multiple_of=15)
    room_class_required = v.field_enum(body, "room_class_required", ROOM_CLASSES)
    skill_code = v.field_str(body, "required_skill_code", max_len=32, upper=True)
    scope_level = v.field_enum(body, "required_scope_level", SCOPE_LEVELS)
    base_price = v.field_int(body, "base_price_cents", minimum=1)
    contraindications = v.field_str_array(body, "contraindication_codes",
                                         required=False, default=[])
    product_line = v.field_str(body, "retail_product_line", max_len=200)
    consent_version = v.field_str(body, "required_consent_version", max_len=64)
    high_demand = v.field_bool(body, "high_demand", required=False, default=False)

    for row in db.treatment_types.values():
        if row["code"] == code:
            raise ApiError(errors.ERR_DUPLICATE_CODE,
                           "Treatment type code '%s' already exists." % code)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "code": code,
        "name": name,
        "duration_minutes": duration,
        "room_class_required": room_class_required,
        "required_skill_code": skill_code,
        "required_scope_level": scope_level,
        "base_price_cents": base_price,
        "contraindication_codes": list(contraindications or []),
        "retail_product_line": product_line,
        "required_consent_version": consent_version,
        "high_demand": bool(high_demand),
    })
    db.treatment_types[entity["id"]] = entity
    return envelope.created(entity)


# --------------------------------------------------------------------------
# treatment rooms
# --------------------------------------------------------------------------

@bp.route("/treatment-rooms", methods=["POST"])
def create_room():
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    code = v.field_str(body, "code", max_len=24)
    room_class = v.field_enum(body, "room_class", ROOM_CLASSES)
    capacity = v.field_int(body, "capacity_guests", minimum=1, maximum=2)
    turnover = v.field_int(body, "turnover_buffer_minutes", minimum=0, maximum=60)
    hourly_cost = v.field_int(body, "hourly_fixed_cost_cents", minimum=0)
    status = v.field_enum(body, "status", ROOM_STATUSES, required=False,
                          default="ACTIVE")

    for row in db.rooms.values():
        if row["code"] == code:
            raise ApiError(errors.ERR_DUPLICATE_CODE,
                           "Room code '%s' already exists." % code)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "code": code,
        "room_class": room_class,
        "capacity_guests": capacity,
        "turnover_buffer_minutes": turnover,
        "hourly_fixed_cost_cents": hourly_cost,
        "status": status,
        "booked_minutes_total": 0,
    })
    db.rooms[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/treatment-rooms/<room_id>", methods=["GET"])
def read_room(room_id):
    auth.authenticate(auth.SPA_DIRECTOR, auth.SPA_COORDINATOR, auth.COMPLIANCE_OFFICER)
    room = domain.find_room(room_id)
    return envelope.ok(room)


@bp.route("/treatment-rooms/<room_id>", methods=["PATCH"])
def patch_room(room_id):
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    status = v.field_enum(body, "status", ROOM_STATUSES)
    room = domain.find_room(room_id)

    room["status"] = status
    touch(room)

    appointments = domain.appointments_of_room(room["id"])
    if status == "ACTIVE":
        domain.run_reclear_cascade(appointments)
    else:
        domain.run_block_cascade(appointments)
    return envelope.ok(room)


# --------------------------------------------------------------------------
# therapists
# --------------------------------------------------------------------------

@bp.route("/therapists", methods=["POST"])
def create_therapist():
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    full_name = v.field_str(body, "full_name", max_len=200)
    employment_type = v.field_enum(body, "employment_type", EMPLOYMENT_TYPES)
    commission_tier = v.field_enum(body, "commission_tier", COMMISSION_TIERS)
    hourly_cost = v.field_int(body, "base_hourly_cost_cents", minimum=0)
    state_code = v.field_str(body, "practice_state_code", min_len=2, max_len=2,
                             pattern=STATE_PATTERN)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "full_name": full_name,
        "employment_type": employment_type,
        "commission_tier": commission_tier,
        "base_hourly_cost_cents": hourly_cost,
        "practice_state_code": state_code,
        "status": "ACTIVE",
        "suspension_reason": None,
        "assigned_minutes_total": 0,
    })
    db.therapists[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/therapists/<therapist_id>", methods=["GET"])
def read_therapist(therapist_id):
    caller = auth.authenticate(auth.SPA_DIRECTOR, auth.SPA_COORDINATOR,
                               auth.COMPLIANCE_OFFICER, auth.THERAPIST)
    therapist = domain.find_therapist(therapist_id)
    auth.require_therapist_owner(caller, therapist["id"])
    return envelope.ok(therapist)


@bp.route("/therapists/<therapist_id>/suspend", methods=["POST"])
def suspend_therapist(therapist_id):
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    permanent = v.field_bool(body, "permanent", required=False, default=False)
    v.field_str(body, "reason_note", required=False, default=None, max_len=500)
    therapist = domain.find_therapist(therapist_id)

    if permanent:
        if therapist["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(errors.ERR_INVALID_THERAPIST_STATE,
                           "A therapist in status '%s' cannot be suspended."
                           % therapist["status"])
        therapist["status"] = "INACTIVE"
    else:
        if therapist["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_THERAPIST_STATE,
                           "Only an ACTIVE therapist may be suspended.")
        therapist["status"] = "SUSPENDED"
    therapist["suspension_reason"] = "DIRECTOR_ACTION"
    touch(therapist)

    domain.run_block_cascade(domain.appointments_of_therapist(therapist["id"]))
    return envelope.ok(therapist)


@bp.route("/therapists/<therapist_id>/reinstate", methods=["POST"])
def reinstate_therapist(therapist_id):
    auth.authenticate(auth.SPA_DIRECTOR)
    v.json_body()
    therapist = domain.find_therapist(therapist_id)

    if therapist["status"] != "SUSPENDED":
        raise ApiError(errors.ERR_INVALID_THERAPIST_STATE,
                       "Only a SUSPENDED therapist may be reinstated.")

    verified = domain.verified_licenses(therapist)
    if not verified:
        raise ApiError(errors.ERR_LICENSE_NOT_VERIFIED,
                       "The therapist holds no VERIFIED licence.")
    if not any(domain.unexpired(l) for l in verified):
        raise ApiError(errors.ERR_LICENSE_EXPIRED,
                       "Every VERIFIED licence of the therapist has lapsed.")

    therapist["status"] = "ACTIVE"
    therapist["suspension_reason"] = None
    touch(therapist)

    domain.run_reclear_cascade(domain.appointments_of_therapist(therapist["id"]))
    return envelope.ok(therapist)


# --------------------------------------------------------------------------
# shift blocks
# --------------------------------------------------------------------------

@bp.route("/therapists/<therapist_id>/shift-blocks", methods=["POST"])
def create_shift_block(therapist_id):
    auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR)
    body = v.json_body()
    block_type = v.field_enum(body, "block_type", BLOCK_TYPES)
    start_at = v.field_instant(body, "start_at")
    end_at = v.field_instant(body, "end_at")
    note = v.field_str(body, "note", required=False, default=None, max_len=500)
    if end_at <= start_at:
        v.bad("Field 'end_at' must be strictly after 'start_at'.")
    therapist = domain.find_therapist(therapist_id)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "therapist_id": therapist["id"],
        "block_type": block_type,
        "start_at": start_at,
        "end_at": end_at,
        "note": note,
    })
    db.shift_blocks[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/therapists/<therapist_id>/shift-blocks", methods=["GET"])
def list_shift_blocks(therapist_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR, auth.THERAPIST)
    limit, offset = v.pagination()
    block_type = v.query_enum("block_type", BLOCK_TYPES)
    from_at = v.query_instant("from_at")
    to_at = v.query_instant("to_at")
    therapist = domain.find_therapist(therapist_id)
    auth.require_therapist_owner(caller, therapist["id"])

    rows = domain.shift_blocks_of(therapist["id"])
    if block_type is not None:
        rows = [r for r in rows if r["block_type"] == block_type]
    if from_at is not None:
        rows = [r for r in rows if r["start_at"] >= from_at]
    if to_at is not None:
        rows = [r for r in rows if r["start_at"] <= to_at]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)
