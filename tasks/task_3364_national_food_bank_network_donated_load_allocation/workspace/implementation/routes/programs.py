"""Retail store donation programs and pickup scheduling / completion / misses."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import envelope
import serializers
import store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_CERTIFIED,
    ERR_MEMBER_NOT_FOUND,
    ERR_MEMBER_SUSPENDED,
    ERR_PICKUP_NOT_FOUND,
    ERR_PICKUP_NOT_SCHEDULED,
    ERR_PICKUP_WINDOW_INVALID,
    ERR_PICKUP_WINDOW_OVERLAP,
    ERR_PROGRAM_NOT_FOUND,
    fail,
)
from services import programs as program_svc

bp = Blueprint("programs", __name__)

PICKUP_FREQUENCIES = ("DAILY", "WEEKLY", "BIWEEKLY")
PICKUP_STATUSES = ("SCHEDULED", "COMPLETED", "MISSED")
BUFFER = timedelta(hours=24)
COMPLETION_GRACE = timedelta(hours=48)


def get_program_or_404(program_id):
    program = store.programs.get(program_id)
    if program is None:
        fail(ERR_PROGRAM_NOT_FOUND, "no store donation program matches id %s" % program_id)
    return program


def get_pickup_or_404(pickup_id):
    pickup = store.pickups.get(pickup_id)
    if pickup is None:
        fail(ERR_PICKUP_NOT_FOUND, "no store pickup matches id %s" % pickup_id)
    return pickup


def _owning_member(program, user_id, role):
    auth.require_owning_member(user_id, role, program["member_id"])


@bp.route("/network/store-programs", methods=["POST"])
def create_program():
    user_id, role = auth.require_roles("MemberFoodBank", "NetworkAdmin")
    data = auth.json_body()

    member_id = auth.req_str(data, "member_id")
    store_name = auth.req_str(data, "store_name")
    store_chain = auth.req_str(data, "store_chain")
    frequency = auth.req_enum(data, "pickup_frequency", PICKUP_FREQUENCIES)
    expected = auth.req_int(data, "expected_weekly_lbs")
    if expected < 0:
        fail(ERR_INVALID_REQUEST, "expected_weekly_lbs must be zero or greater")

    auth.require_owning_member(user_id, role, member_id)
    member = store.members.get(member_id)
    if member is None:
        fail(ERR_MEMBER_NOT_FOUND, "no member food bank matches id %s" % member_id)
    if member["certification_status"] == "SUSPENDED":
        fail(ERR_MEMBER_SUSPENDED, "a suspended member may not register a store program")

    program = store.new_record(
        member_id=member["id"],
        store_name=store_name,
        store_chain=store_chain,
        pickup_frequency=frequency,
        expected_weekly_lbs=expected,
        program_status="ACTIVE" if member["certification_status"] == "CERTIFIED" else "PENDING",
    )
    store.insert("programs", program)
    return envelope.ok_object(serializers.program(program), 201)


@bp.route("/network/store-programs/<program_id>", methods=["GET"])
def read_program(program_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    return envelope.ok_object(serializers.program(get_program_or_404(program_id)))


@bp.route("/network/store-programs/<program_id>/pickups", methods=["POST"])
def schedule_pickup(program_id):
    user_id, role = auth.require_roles("MemberFoodBank")
    data = auth.json_body()

    scheduled_date = clock.parse_iso(auth.req_str(data, "scheduled_date"))
    window_start = clock.parse_iso(auth.req_str(data, "window_start"))
    window_end = clock.parse_iso(auth.req_str(data, "window_end"))

    program = get_program_or_404(program_id)
    _owning_member(program, user_id, role)
    member = store.members.get(program["member_id"])
    if member is not None:
        if member["certification_status"] == "SUSPENDED":
            fail(ERR_MEMBER_SUSPENDED, "a suspended member may not schedule pickups")
        if member["certification_status"] != "CERTIFIED":
            fail(ERR_MEMBER_NOT_CERTIFIED,
                 "scheduling a pickup requires a CERTIFIED member")
    if program["program_status"] != "ACTIVE":
        fail(ERR_MEMBER_NOT_CERTIFIED, "pickups may only be scheduled for an ACTIVE program")

    if window_start >= window_end:
        fail(ERR_PICKUP_WINDOW_INVALID,
             "window_start must be strictly before window_end")
    if scheduled_date.date() < clock.today():
        fail(ERR_PICKUP_WINDOW_INVALID,
             "scheduled_date may not be earlier than the current logical clock date")
    if (window_start.date() != scheduled_date.date()
            or window_end.date() != scheduled_date.date()):
        fail(ERR_PICKUP_WINDOW_INVALID,
             "the pickup window must fall on scheduled_date")

    for other in program_svc.pickups_of(program["id"]):
        if other["pickup_status"] != "SCHEDULED":
            continue
        other_start = other["window_start"]
        other_end = other["window_end"]
        if window_start < other_end and other_start < window_end:
            fail(ERR_PICKUP_WINDOW_OVERLAP,
                 "the window overlaps another SCHEDULED pickup of this program")
        if window_start < other_end + BUFFER and other_start < window_end + BUFFER:
            fail(ERR_PICKUP_WINDOW_OVERLAP,
                 "pickups of the same program must keep 24 hours between them")

    pickup = store.new_record(
        program_id=program["id"],
        scheduled_date=scheduled_date,
        window_start=window_start,
        window_end=window_end,
        pickup_status="SCHEDULED",
        collected_lbs=0,
        meal_equivalent=0,
    )
    store.insert("pickups", pickup)
    return envelope.ok_object(serializers.pickup(pickup), 201)


@bp.route("/network/store-programs/<program_id>/pickups", methods=["GET"])
def list_pickups(program_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    program = get_program_or_404(program_id)
    rows = program_svc.pickups_of(program["id"])
    status_filter = request.args.get("pickup_status")
    if status_filter:
        rows = [p for p in rows if p["pickup_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.pickup(p) for p in page], limit, offset, total)


@bp.route("/network/store-pickups/<pickup_id>/complete", methods=["POST"])
def complete_pickup(pickup_id):
    user_id, role = auth.require_roles("MemberFoodBank")
    data = auth.json_body()
    collected = auth.req_int(data, "collected_lbs")
    if collected < 0:
        fail(ERR_INVALID_REQUEST, "collected_lbs must be zero or greater")

    pickup = get_pickup_or_404(pickup_id)
    program = store.programs.get(pickup["program_id"])
    if program is not None:
        _owning_member(program, user_id, role)
    if pickup["pickup_status"] != "SCHEDULED":
        fail(ERR_PICKUP_NOT_SCHEDULED, "the pickup is not SCHEDULED")

    now = clock.now()
    if not (pickup["window_start"] <= now <= pickup["window_end"]
            or now <= pickup["window_end"] + COMPLETION_GRACE):
        fail(ERR_PICKUP_WINDOW_INVALID,
             "the pickup may only be completed inside its window or within 48 hours of it")

    pickup["collected_lbs"] = collected
    pickup["meal_equivalent"] = program_svc.meal_equivalent(collected)
    pickup["pickup_status"] = "COMPLETED"
    store.touch(pickup)
    return envelope.ok_object(serializers.pickup(pickup))


@bp.route("/network/store-pickups/<pickup_id>/miss", methods=["POST"])
def miss_pickup(pickup_id):
    user_id, role = auth.require_roles("MemberFoodBank")
    pickup = get_pickup_or_404(pickup_id)
    program = store.programs.get(pickup["program_id"])
    if program is not None:
        _owning_member(program, user_id, role)
    if pickup["pickup_status"] != "SCHEDULED":
        fail(ERR_PICKUP_NOT_SCHEDULED, "the pickup is not SCHEDULED")

    program_svc.mark_missed(pickup)
    return envelope.ok_object(serializers.pickup(pickup))
