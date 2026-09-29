"""Programs: drafting, publication, room reservations, registration."""

from flask import Blueprint, request

import calc
import derive
import lookup
import revision
import services
import store
import validate
from core import clock, date_of
from errors import ApiError
from web import Arr, Obj, endpoint

bp = Blueprint("programs", __name__)

MANAGER = ("ProgramManager",)
STAFF = ("ProgramManager", "ProgramCoordinator")

AGE_GROUPS = ("EARLY_CHILDHOOD", "SCHOOL_AGE", "TEEN", "ADULT", "ALL_AGES")
DELIVERY_MODES = ("IN_BRANCH", "PARTNER_SITE")
PARTNER_TYPES = ("NONE", "SCHOOL", "PARKS", "NONPROFIT")
REGISTRATION_POLICIES = ("REGISTRATION", "DROP_IN")
ACCOMMODATIONS = (
    "ASL_INTERPRETER",
    "SENSORY_QUIET_HOUR",
    "WHEELCHAIR_LAYOUT",
    "LARGE_PRINT_HANDOUTS",
)

SCHEDULABLE = ("DRAFT", "SCHEDULED")


def _check_window(start_utc, end_utc):
    """Ladder step 29: ordered and not in the past."""
    if start_utc >= end_utc:
        raise ApiError("ERR_INVALID_PROGRAM_WINDOW")
    now = clock.now()
    if start_utc < now or end_utc < now:
        raise ApiError("ERR_INVALID_PROGRAM_WINDOW")


def _check_partner_insurance(program, end_utc):
    """Ladder step 21: the partner certificate must cover the program."""
    expires_on = program["partner_insurance_expires_on"]
    if expires_on is None or expires_on < date_of(end_utc):
        raise ApiError("ERR_PARTNER_INSURANCE_LAPSED")


def _live_reservations(program_id, statuses):
    return [
        r
        for r in derive.program_reservations(program_id)
        if r["status"] in statuses
    ]


# ------------------------------------------------------------------ reads

@bp.route("/library/programs/<program_id>", methods=["GET"])
@endpoint(STAFF)
def get_program(user_id, role, program_id):
    return Obj("programs", lookup.program(program_id))


@bp.route("/library/programs", methods=["GET"])
@endpoint(STAFF)
def list_programs(user_id, role):
    programs = store.all_of("programs")
    for field in (
        "branch_id",
        "challenge_id",
        "operational_status",
        "compliance_status",
    ):
        value = request.args.get(field)
        if value is not None:
            programs = [p for p in programs if p[field] == value]
    return Arr("programs", programs)


# ------------------------------------------------------------------ drafting

@bp.route("/library/programs", methods=["POST"])
@endpoint(STAFF, mutating=True)
def create_program(user_id, role):
    payload = validate.body()
    branch_id = validate.string_field(payload, "branch_id")
    challenge_id = validate.string_field(
        payload, "challenge_id", required=False, default=None
    )
    title = validate.string_field(payload, "title")
    age_group = validate.enum_field(payload, "age_group", AGE_GROUPS)
    delivery_mode = validate.enum_field(payload, "delivery_mode", DELIVERY_MODES)
    partner_type = validate.enum_field(
        payload, "partner_type", PARTNER_TYPES, required=False, default="NONE"
    )
    partner_org_name = validate.string_field(
        payload, "partner_org_name", required=False, default=None
    )
    partner_expires_on = validate.date_field(
        payload, "partner_insurance_expires_on", required=False, default=None
    )
    registration_policy = validate.enum_field(
        payload, "registration_policy", REGISTRATION_POLICIES
    )
    start_utc = validate.instant_field(payload, "start_utc")
    end_utc = validate.instant_field(payload, "end_utc")
    attendance_target = validate.integer_field(
        payload, "attendance_target", minimum=1
    )
    attendance_cap = validate.integer_field(payload, "attendance_cap", minimum=1)
    if attendance_cap < attendance_target:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "attendance_cap must be at least attendance_target.",
        )
    accommodations = validate.enum_array_field(
        payload, "accessibility_accommodations", ACCOMMODATIONS, default=[]
    )
    supply_sku = validate.string_field(payload, "supply_sku")
    supply_units = validate.integer_field(
        payload, "supply_units_per_attendee", minimum=0
    )
    materials_budget = validate.integer_field(
        payload, "materials_budget_cents", minimum=0
    )
    presenter_budget = validate.integer_field(
        payload, "presenter_fee_budget_cents", minimum=0
    )

    branch = lookup.branch(branch_id)
    if challenge_id is not None:
        lookup.challenge(challenge_id)

    _check_window(start_utc, end_utc)

    # Ladder step 30: partner fields coherent with the delivery mode.
    if delivery_mode == "PARTNER_SITE":
        if (
            partner_type == "NONE"
            or partner_org_name is None
            or partner_org_name.strip() == ""
            or partner_expires_on is None
        ):
            raise ApiError("ERR_PARTNER_FIELDS_REQUIRED")
    else:
        if (
            partner_type != "NONE"
            or partner_org_name is not None
            or partner_expires_on is not None
        ):
            raise ApiError("ERR_PARTNER_FIELDS_REQUIRED")

    program = store.new_entity(
        "programs",
        {
            "branch_id": branch["id"],
            "challenge_id": challenge_id,
            "title": title,
            "age_group": age_group,
            "serves_minors": calc.serves_minors(age_group),
            "delivery_mode": delivery_mode,
            "partner_type": partner_type,
            "partner_org_name": partner_org_name,
            "partner_insurance_expires_on": partner_expires_on,
            "registration_policy": registration_policy,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "attendance_target": attendance_target,
            "attendance_cap": attendance_cap,
            "accessibility_accommodations": accommodations,
            "supply_sku": supply_sku,
            "supply_units_per_attendee": supply_units,
            "materials_budget_cents": materials_budget,
            "presenter_fee_budget_cents": presenter_budget,
            "operational_status": "DRAFT",
            "compliance_status": "UNVERIFIED",
            "registered_count": 0,
            "registrant_references": [],
            "confirmed_room_capacity": 0,
            "supply_draw_lines": [],
            "materials_committed_cents": 0,
            "materials_spent_cents": 0,
            "presenter_fee_committed_cents": 0,
            "presenter_fee_spent_cents": 0,
            "verified_registrant_attendance": 0,
            "drop_in_headcount": 0,
            "surveys_collected": 0,
            "gross_attendance": 0,
            "no_show_count": 0,
            "attendance_attainment_funder_pct": 0.0,
            "attendance_attainment_internal_pct": 0.0,
            "survey_response_rate_pct": 0.0,
            "closure_reason": None,
        },
    )
    return Obj("programs", program, 201)


@bp.route("/library/programs/<program_id>/schedule", methods=["POST"])
@endpoint(STAFF, mutating=True)
def schedule_program(user_id, role, program_id):
    payload = validate.optional_body()
    new_start = validate.instant_field(
        payload, "start_utc", required=False, default=None
    )
    new_end = validate.instant_field(payload, "end_utc", required=False, default=None)
    program = lookup.program(program_id)

    if program["operational_status"] not in SCHEDULABLE:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    start_utc = new_start if new_start is not None else program["start_utc"]
    end_utc = new_end if new_end is not None else program["end_utc"]

    if program["delivery_mode"] == "PARTNER_SITE":
        _check_partner_insurance(program, end_utc)
    else:
        if not _live_reservations(program["id"], ("HELD", "CONFIRMED")):
            raise ApiError("ERR_NO_CONFIRMED_ROOM")

    _check_window(start_utc, end_utc)
    if program["attendance_cap"] < program["attendance_target"]:
        raise ApiError("ERR_INVALID_REQUEST")

    moved = new_start is not None or new_end is not None
    program["start_utc"] = start_utc
    program["end_utc"] = end_utc
    if moved:
        # A moved program must be re-booked: its held bookings are released.
        for reservation in derive.program_reservations(program["id"]):
            if reservation["status"] == "HELD":
                reservation["status"] = "RELEASED"
                revision.mark(reservation)
    program["operational_status"] = "SCHEDULED"
    revision.mark(program)
    return Obj("programs", program)


# -------------------------------------------------------------- reservations

@bp.route("/library/reservations/<reservation_id>", methods=["GET"])
@endpoint(STAFF)
def get_reservation(user_id, role, reservation_id):
    return Obj("reservations", lookup.reservation(reservation_id))


@bp.route("/library/reservations", methods=["GET"])
@endpoint(STAFF)
def list_reservations(user_id, role):
    reservations = store.all_of("reservations")
    for field in ("program_id", "room_id", "status"):
        value = request.args.get(field)
        if value is not None:
            reservations = [r for r in reservations if r[field] == value]
    return Arr("reservations", reservations)


def _occupancy_conflict(room_id, occupancy_start, occupancy_end, exclude_program_id,
                        exclude_reservation_id):
    """Half-open comparison against every other live booking of the room."""
    for other in derive.room_reservations(room_id):
        if other["status"] not in ("HELD", "CONFIRMED"):
            continue
        if exclude_reservation_id and other["id"] == exclude_reservation_id:
            continue
        if exclude_program_id and other["program_id"] == exclude_program_id:
            continue
        if calc.intervals_overlap_half_open(
            occupancy_start,
            occupancy_end,
            other["occupancy_start_utc"],
            other["occupancy_end_utc"],
        ):
            return True
    return False


@bp.route("/library/programs/<program_id>/reservations", methods=["POST"])
@endpoint(STAFF, mutating=True)
def create_reservation(user_id, role, program_id):
    payload = validate.body()
    room_id = validate.string_field(payload, "room_id")
    start_utc = validate.instant_field(payload, "start_utc")
    end_utc = validate.instant_field(payload, "end_utc")
    setup_minutes = validate.integer_field(payload, "setup_minutes", minimum=0)
    teardown_minutes = validate.integer_field(payload, "teardown_minutes", minimum=0)
    expected_version = validate.integer_field(payload, "expected_program_version")

    program = lookup.program(program_id)
    room = lookup.room(room_id)

    # Ladder step 9: the caller must prove it saw the current program.
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")

    if program["operational_status"] not in SCHEDULABLE:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")

    held = None
    for existing in derive.program_reservations(program["id"]):
        if existing["status"] == "CONFIRMED":
            raise ApiError("ERR_RESERVATION_STATE_INVALID")
        if existing["status"] == "HELD":
            held = existing

    if room["status"] != "AVAILABLE":
        raise ApiError("ERR_ROOM_OUT_OF_SERVICE")

    accommodations = program["accessibility_accommodations"]
    for accommodation in accommodations:
        required = calc.ACCESSIBILITY_ROOM_REQUIREMENT.get(accommodation)
        if required and required not in room["accessibility_features"]:
            raise ApiError("ERR_ACCESSIBILITY_UNSUPPORTED")

    if setup_minutes < calc.required_setup_minutes(room, accommodations):
        raise ApiError("ERR_SETUP_BUFFER_TOO_SHORT")
    if teardown_minutes < room["min_teardown_minutes"]:
        raise ApiError("ERR_SETUP_BUFFER_TOO_SHORT")

    if start_utc > program["start_utc"] or end_utc < program["end_utc"]:
        raise ApiError("ERR_RESERVATION_WINDOW_MISMATCH")

    occupancy_start, occupancy_end = calc.occupancy_interval(
        start_utc, end_utc, setup_minutes, teardown_minutes
    )
    if _occupancy_conflict(
        room["id"], occupancy_start, occupancy_end, program["id"], None
    ):
        raise ApiError("ERR_ROOM_DOUBLE_BOOKED")

    if held is not None:
        held["status"] = "SUPERSEDED"
        revision.mark(held)

    reservation = store.new_entity(
        "reservations",
        {
            "program_id": program["id"],
            "room_id": room["id"],
            "start_utc": start_utc,
            "end_utc": end_utc,
            "setup_minutes": setup_minutes,
            "teardown_minutes": teardown_minutes,
            "occupancy_start_utc": occupancy_start,
            "occupancy_end_utc": occupancy_end,
            "effective_capacity_seats": calc.room_effective_capacity(
                room["capacity_seats"], accommodations
            ),
            "status": "HELD",
        },
    )
    revision.mark(program)
    return Obj("reservations", reservation, 201)


@bp.route("/library/reservations/<reservation_id>/confirm", methods=["POST"])
@endpoint(STAFF, mutating=True)
def confirm_reservation(user_id, role, reservation_id):
    reservation = lookup.reservation(reservation_id)
    if reservation["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    program = store.get("programs", reservation["program_id"])
    if program is None or program["operational_status"] not in SCHEDULABLE:
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    room = store.get("rooms", reservation["room_id"])
    if room is None or room["status"] != "AVAILABLE":
        raise ApiError("ERR_ROOM_OUT_OF_SERVICE")
    if _occupancy_conflict(
        reservation["room_id"],
        reservation["occupancy_start_utc"],
        reservation["occupancy_end_utc"],
        None,
        reservation["id"],
    ):
        raise ApiError("ERR_ROOM_DOUBLE_BOOKED")

    reservation["status"] = "CONFIRMED"
    program["confirmed_room_capacity"] = reservation["effective_capacity_seats"]
    revision.mark(reservation)
    revision.mark(program)
    return Obj("reservations", reservation)


# ------------------------------------------------------------- registrations

@bp.route("/library/programs/<program_id>/registrations", methods=["POST"])
@endpoint(STAFF, mutating=True)
def create_registration(user_id, role, program_id):
    payload = validate.body()
    reference = validate.string_field(payload, "registrant_reference")
    seats = validate.integer_field(
        payload, "seats", required=False, default=1, minimum=1
    )
    program = lookup.program(program_id)

    if program["operational_status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if program["compliance_status"] == "BLOCKED":
        raise ApiError("ERR_PROGRAM_COMPLIANCE_BLOCKED")
    if program["registration_policy"] != "REGISTRATION":
        raise ApiError("ERR_DROP_IN_NO_REGISTRATION")
    if clock.now() >= program["start_utc"]:
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED")
    if reference in program["registrant_references"]:
        raise ApiError("ERR_DUPLICATE_REGISTRANT")

    ceiling = program["attendance_cap"]
    if program["confirmed_room_capacity"] > 0:
        ceiling = min(ceiling, program["confirmed_room_capacity"])
    if program["registered_count"] + seats > ceiling:
        raise ApiError("ERR_PROGRAM_AT_CAPACITY")

    program["registered_count"] += seats
    program["registrant_references"] = list(program["registrant_references"]) + [
        reference
    ]
    revision.mark(program)
    return Obj("programs", program)
