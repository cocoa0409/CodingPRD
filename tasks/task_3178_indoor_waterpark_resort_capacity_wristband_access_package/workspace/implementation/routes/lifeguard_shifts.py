"""Lifeguard shift endpoints: scheduling and rotation discipline."""

from datetime import timedelta

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from db import date_from_service_date, parse_iso, service_date_of
from services import common, engine

bp = Blueprint("lifeguard_shifts", __name__)

DECLARED_CREATE = (
    "attraction_id",
    "staffer_name",
    "certification_code",
    "shift_date",
    "start_minute",
    "end_minute",
    "rotation_minutes",
)

CERTIFICATIONS = ("LIFEGUARD", "NONE")


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def shifts_for(resort_id, staffer_name, shift_date):
    return [
        s for s in _db.store().lifeguard_shifts.values()
        if s.get("resort_id") == resort_id
        and s.get("staffer_name") == staffer_name
        and s.get("shift_date") == shift_date
    ]


def window_bounds(shift):
    start = shift.get("start_minute")
    end = shift.get("end_minute")
    return start, end


def window_instant(shift_date, minute):
    return date_from_service_date(shift_date) + timedelta(minutes=minute)


@bp.route("/resorts/<resort_id>/lifeguard-shifts", methods=["POST"])
def create_shift(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "AquaticsManager")
    common.get_resort(resort_id)

    attraction = common.fetch("attraction", v.required_str(payload, "attraction_id"), resort_id)
    staffer_name = v.required_str(payload, "staffer_name")
    certification = v.in_enum(
        v.required_str(payload, "certification_code"), "certification_code", CERTIFICATIONS
    )
    shift_date = v.required_service_date(payload, "shift_date")
    start_minute = v.required_int(payload, "start_minute")
    v.in_range(start_minute, "start_minute", low=0, high=1439)
    end_minute = v.required_int(payload, "end_minute")
    v.in_range(end_minute, "end_minute", low=start_minute + 1, high=1440)
    if end_minute <= start_minute:
        raise errors.invalid_request("end_minute must be greater than start_minute.")
    rotation_minutes = v.required_int(payload, "rotation_minutes")
    v.in_range(rotation_minutes, "rotation_minutes", low=1)

    shift = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "attraction_id": attraction["id"],
        "staffer_name": staffer_name,
        "certification_code": certification,
        "shift_date": shift_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "rotation_minutes": rotation_minutes,
        "shift_status": "SCHEDULED",
    }
    _db.store().lifeguard_shifts[shift["id"]] = shift
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 201


@bp.route("/resorts/<resort_id>/lifeguard-shifts", methods=["GET"])
def list_shifts(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        s for s in _db.store().lifeguard_shifts.values() if s.get("resort_id") == resort_id
    ]
    attraction_id = v.query_str("attraction_id")
    if attraction_id:
        rows = [s for s in rows if s.get("attraction_id") == attraction_id]
    staffer_name = v.query_str("staffer_name")
    if staffer_name:
        rows = [s for s in rows if s.get("staffer_name") == staffer_name]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("lifeguard_shift", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/lifeguard-shifts/<shift_id>", methods=["GET"])
def get_shift(resort_id, shift_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)
    shift = common.fetch("lifeguard_shift", shift_id, resort_id)
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 200


@bp.route("/resorts/<resort_id>/lifeguard-shifts/<shift_id>/start", methods=["POST"])
def start_shift(resort_id, shift_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "AquaticsManager")
    common.get_resort(resort_id)
    shift = common.fetch("lifeguard_shift", shift_id, resort_id)

    if shift["shift_status"] != "SCHEDULED":
        raise errors.invalid_state()

    attraction = common.get("attraction", shift["attraction_id"])
    # PRD 3.6: "the staffer's `certification_code` must equal the target
    # attraction's `required_certification` — an uncertified staffer cannot be
    # posted to an attraction that requires a lifeguard".  The forbidden
    # direction is NONE certified onto a LIFEGUARD attraction; an attraction
    # that requires no certification accepts a certified staffer as well.
    if attraction is None or (
        attraction["required_certification"] == "LIFEGUARD"
        and shift["certification_code"] != "LIFEGUARD"
    ):
        raise errors.shift_rotation_violation(
            "The staffer's certification does not match the attraction's requirement."
        )

    start, end = window_bounds(shift)
    for other in shifts_for(resort_id, shift["staffer_name"], shift["shift_date"]):
        if other["id"] == shift["id"]:
            continue
        if other.get("shift_status") in ("ON_DUTY", "ROTATED"):
            o_start, o_end = window_bounds(other)
            if overlaps(start, end, o_start, o_end):
                raise errors.shift_rotation_violation(
                    "The staffer already posts a live overlapping shift."
                )

    if (end - start) > shift["rotation_minutes"] + common.LIFEGUARD_MAX_CONSECUTIVE_MINUTES:
        raise errors.shift_rotation_violation(
            "The shift exceeds its rotation allowance plus the consecutive maximum."
        )

    for other in shifts_for(resort_id, shift["staffer_name"], shift["shift_date"]):
        if other.get("shift_status") != "COMPLETED":
            continue
        o_start, o_end = window_bounds(other)
        gap = max(o_start - end, start - o_end)
        if gap < common.LIFEGUARD_ROTATION_BUFFER_MINUTES:
            raise errors.shift_rotation_violation(
                "The shift abuts a completed shift inside the rotation buffer."
            )

    shift["shift_status"] = "ON_DUTY"
    common.touch(shift)
    common.recompute_attraction_status(resort_id, shift["attraction_id"])
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 200


@bp.route("/resorts/<resort_id>/lifeguard-shifts/<shift_id>/rotate", methods=["POST"])
def rotate_shift(resort_id, shift_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "AquaticsManager")
    common.get_resort(resort_id)
    shift = common.fetch("lifeguard_shift", shift_id, resort_id)

    if shift["shift_status"] != "ON_DUTY":
        raise errors.invalid_state()

    start, end = window_bounds(shift)
    for other in shifts_for(resort_id, shift["staffer_name"], shift["shift_date"]):
        if other["id"] == shift["id"]:
            continue
        o_start, o_end = window_bounds(other)
        if other.get("shift_status") == "ROTATED" and overlaps(start, end, o_start, o_end):
            raise errors.shift_rotation_violation("An overlapping rotated shift already stands.")
        if other.get("shift_status") == "ON_DUTY" and o_start < end:
            raise errors.shift_rotation_violation(
                "The staffer would hold two live postings at once."
            )

    shift["shift_status"] = "ROTATED"
    common.touch(shift)
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 200


@bp.route("/resorts/<resort_id>/lifeguard-shifts/<shift_id>/resume", methods=["POST"])
def resume_shift(resort_id, shift_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "AquaticsManager")
    common.get_resort(resort_id)
    shift = common.fetch("lifeguard_shift", shift_id, resort_id)

    if shift["shift_status"] != "ROTATED":
        raise errors.invalid_state()

    start, end = window_bounds(shift)
    for other in shifts_for(resort_id, shift["staffer_name"], shift["shift_date"]):
        if other["id"] == shift["id"]:
            continue
        if other.get("shift_status") != "ON_DUTY":
            continue
        o_start, o_end = window_bounds(other)
        if overlaps(start, end, o_start, o_end):
            raise errors.shift_rotation_violation("An overlapping live posting already stands.")

    window_start = window_instant(shift["shift_date"], start)
    window_end = window_instant(shift["shift_date"], end)
    for log in _db.store().water_quality_logs.values():
        if log.get("resort_id") != resort_id:
            continue
        if log.get("attraction_id") != shift["attraction_id"]:
            continue
        sampled = parse_iso(log.get("sampled_at"))
        if sampled is None:
            continue
        if service_date_of(sampled) != shift["shift_date"]:
            continue
        if window_start <= sampled < window_end and log.get("log_status") != "PASS":
            raise errors.invalid_state(
                "A staffer may not resume posting to water that has failed a reading."
            )

    shift["shift_status"] = "ON_DUTY"
    common.touch(shift)
    common.recompute_attraction_status(resort_id, shift["attraction_id"])
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 200


@bp.route("/resorts/<resort_id>/lifeguard-shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(resort_id, shift_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "AquaticsManager")
    common.get_resort(resort_id)
    shift = common.fetch("lifeguard_shift", shift_id, resort_id)

    if shift["shift_status"] not in ("ON_DUTY", "ROTATED"):
        raise errors.invalid_state()

    shift["shift_status"] = "COMPLETED"
    common.touch(shift)
    common.recompute_attraction_status(resort_id, shift["attraction_id"])
    return jsonify(response.success(common.serialise("lifeguard_shift", shift))), 200