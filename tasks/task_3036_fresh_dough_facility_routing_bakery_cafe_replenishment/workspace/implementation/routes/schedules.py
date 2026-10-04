"""Cafe schedules and bake entries (PRD 3.7)."""

import datetime

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import (authorize, require_cafe_owner, ALL_ROLES,
                        ROLE_CAFE_MANAGER)

bp = Blueprint("schedules", __name__)


# ---------------------------------------------------------------------------
# CafeSchedule
# ---------------------------------------------------------------------------
@bp.route("/dough-ops/cafes/<cafe_id>/schedules", methods=["POST"])
def create_schedule(cafe_id):
    authorize(ROLE_CAFE_MANAGER)
    cafe = services.get_or_404(db.cafes, cafe_id, "Cafe")
    require_cafe_owner(cafe_id)
    data = V.body_json(request)
    business_date = V.req_date(data, "business_date")
    for sched in db.cafe_schedules.values():
        if sched["cafe_id"] == cafe_id and sched["business_date"] == business_date:
            raise ApiError("ERR_DUPLICATE",
                           "A schedule already exists for this cafe and business date.")
    row = db.common_fields()
    row.update({
        "cafe_id": cafe_id,
        "business_date": business_date,
        "status": "PLANNED",
    })
    db.cafe_schedules[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules", methods=["GET"])
def list_schedules(cafe_id):
    authorize(*ALL_ROLES)
    services.get_or_404(db.cafes, cafe_id, "Cafe")
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    rows = [r for r in db.cafe_schedules.values()
            if r["cafe_id"] == cafe_id
            and (business_date is None or r["business_date"] == business_date)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/schedules", methods=["GET"])
def list_schedules_flat():
    authorize(*ALL_ROLES)
    cafe_id = request.args.get("cafe_id")
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    rows = [r for r in db.cafe_schedules.values()
            if (cafe_id is None or r["cafe_id"] == cafe_id)
            and (business_date is None or r["business_date"] == business_date)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.cafe_schedules, schedule_id, "Schedule")
    return resp.object_response(resp.serialize(row), 200)


def _get_schedule_under_cafe(cafe_id, schedule_id):
    services.get_or_404(db.cafes, cafe_id, "Cafe")
    schedule = services.get_or_404(db.cafe_schedules, schedule_id, "Schedule")
    if schedule["cafe_id"] != cafe_id:
        raise ApiError("ERR_NOT_FOUND", "Schedule not found under this cafe.")
    return schedule


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/open", methods=["POST"])
def open_schedule(cafe_id, schedule_id):
    authorize(ROLE_CAFE_MANAGER)
    schedule = _get_schedule_under_cafe(cafe_id, schedule_id)
    require_cafe_owner(cafe_id)
    if schedule["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED schedule may be opened.")
    today = db.now_dt().date()
    if today != services.parse_date(schedule["business_date"]):
        raise ApiError("ERR_INVALID_STATE",
                       "A schedule may only be opened on its business date.")
    schedule["status"] = "OPEN"
    db.touch(schedule)
    return resp.object_response(resp.serialize(schedule), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/close", methods=["POST"])
def close_schedule(cafe_id, schedule_id):
    authorize(ROLE_CAFE_MANAGER)
    schedule = _get_schedule_under_cafe(cafe_id, schedule_id)
    require_cafe_owner(cafe_id)
    if schedule["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN schedule may be closed.")
    for entry in db.bake_entries.values():
        if entry["schedule_id"] == schedule_id and \
                entry["status"] not in ("COMPLETED", "DISCARDED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Every bake entry must be COMPLETED or DISCARDED before close.")
    schedule["status"] = "CLOSED"
    db.touch(schedule)
    return resp.object_response(resp.serialize(schedule), 200)


# ---------------------------------------------------------------------------
# BakeEntry
# ---------------------------------------------------------------------------
def _entry_interval(entry):
    start = V.parse_instant(entry["proof_start_at"], "proof_start_at")
    end = start + datetime.timedelta(minutes=entry["proof_minutes"])
    return start, end


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries", methods=["POST"])
def create_bake_entry(cafe_id, schedule_id):
    authorize(ROLE_CAFE_MANAGER)
    schedule = _get_schedule_under_cafe(cafe_id, schedule_id)
    require_cafe_owner(cafe_id)
    data = V.body_json(request)
    cafe_order_id = data.get("cafe_order_id")
    quantity = V.req_int(data, "quantity", minimum=1)
    proof_start_at = V.req_instant(data, "proof_start_at")
    proof_minutes = V.req_int(data, "proof_minutes", minimum=1)
    if not isinstance(cafe_order_id, str) or cafe_order_id not in db.cafe_orders:
        raise ApiError("ERR_NOT_FOUND", "Cafe order not found.")
    order = db.cafe_orders[cafe_order_id]
    if order["cafe_id"] != cafe_id:
        raise ApiError("ERR_NOT_FOUND", "Cafe order not found under this cafe.")

    # Proof-interval overlap within the schedule (half-open [start, end)):
    # back-to-back adjacency is legal.
    new_end = proof_start_at + datetime.timedelta(minutes=proof_minutes)
    for other in db.bake_entries.values():
        if other["schedule_id"] != schedule_id or \
                other["status"] in ("COMPLETED", "DISCARDED"):
            continue
        o_start, o_end = _entry_interval(other)
        if proof_start_at < o_end and o_start < new_end:
            raise ApiError("ERR_STOP_WINDOW_VIOLATION",
                           "The proof interval overlaps another entry on the schedule.")

    row = db.common_fields()
    row.update({
        "schedule_id": schedule_id,
        "cafe_order_id": cafe_order_id,
        "quantity": quantity,
        "proof_start_at": data.get("proof_start_at"),
        "proof_minutes": proof_minutes,
        "status": "SCHEDULED",
    })
    db.bake_entries[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries", methods=["GET"])
def list_bake_entries(cafe_id, schedule_id):
    authorize(*ALL_ROLES)
    _get_schedule_under_cafe(cafe_id, schedule_id)
    cafe_order_id = request.args.get("cafe_order_id")
    status = request.args.get("status")
    rows = [r for r in db.bake_entries.values()
            if r["schedule_id"] == schedule_id
            and (cafe_order_id is None or r["cafe_order_id"] == cafe_order_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/bake-entries", methods=["GET"])
def list_bake_entries_flat():
    authorize(*ALL_ROLES)
    schedule_id = request.args.get("schedule_id")
    cafe_order_id = request.args.get("cafe_order_id")
    status = request.args.get("status")
    rows = [r for r in db.bake_entries.values()
            if (schedule_id is None or r["schedule_id"] == schedule_id)
            and (cafe_order_id is None or r["cafe_order_id"] == cafe_order_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/bake-entries/<entry_id>", methods=["GET"])
def get_bake_entry(entry_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.bake_entries, entry_id, "Bake entry")
    return resp.object_response(resp.serialize(row), 200)


def _get_entry_under(cafe_id, schedule_id, entry_id):
    _get_schedule_under_cafe(cafe_id, schedule_id)
    entry = services.get_or_404(db.bake_entries, entry_id, "Bake entry")
    if entry["schedule_id"] != schedule_id:
        raise ApiError("ERR_NOT_FOUND", "Bake entry not found under this schedule.")
    return entry


def _expiry_instant(order):
    dough_type = db.dough_types[order["dough_type_id"]]
    day = services.parse_date(order["production_date"])
    return datetime.datetime(day.year, day.month, day.day) + \
        datetime.timedelta(hours=dough_type["shelf_life_hours"])


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries/<entry_id>/start-proof",
          methods=["POST"])
def start_proof(cafe_id, schedule_id, entry_id):
    authorize(ROLE_CAFE_MANAGER)
    schedule = _get_schedule_under_cafe(cafe_id, schedule_id)
    entry = _get_entry_under(cafe_id, schedule_id, entry_id)
    require_cafe_owner(cafe_id)
    if entry["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED entry may start proofing.")
    if schedule["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "The schedule must be OPEN to start proofing.")
    order = db.cafe_orders[entry["cafe_order_id"]]
    if order["status"] not in ("DELIVERED", "SHIPPED_SHORT"):
        raise ApiError("ERR_INVALID_STATE",
                       "The supplying order must be DELIVERED or SHIPPED_SHORT.")
    now = db.now_dt()
    proof_start = V.parse_instant(entry["proof_start_at"], "proof_start_at")
    if now < proof_start:
        raise ApiError("ERR_TOO_EARLY", "Proofing may not start before proof_start_at.")
    entry["status"] = "PROOFING"
    db.touch(entry)
    return resp.object_response(resp.serialize(entry), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries/<entry_id>/start-bake",
          methods=["POST"])
def start_bake(cafe_id, schedule_id, entry_id):
    authorize(ROLE_CAFE_MANAGER)
    entry = _get_entry_under(cafe_id, schedule_id, entry_id)
    require_cafe_owner(cafe_id)
    if entry["status"] != "PROOFING":
        raise ApiError("ERR_INVALID_STATE", "Only a PROOFING entry may start baking.")
    now = db.now_dt()
    order = db.cafe_orders[entry["cafe_order_id"]]
    # Priority 9 (safety) outranks priority 14 (proof timing).
    if now >= _expiry_instant(order):
        raise ApiError("ERR_SHELF_LIFE_EXCEEDED", "The dough has expired.")
    proof_start = V.parse_instant(entry["proof_start_at"], "proof_start_at")
    bake_at = proof_start + datetime.timedelta(minutes=entry["proof_minutes"])
    if now < bake_at:
        raise ApiError("ERR_TOO_EARLY", "Baking may not start before the proof has elapsed.")
    entry["status"] = "BAKING"
    db.touch(entry)
    return resp.object_response(resp.serialize(entry), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries/<entry_id>/complete",
          methods=["POST"])
def complete_bake_entry(cafe_id, schedule_id, entry_id):
    authorize(ROLE_CAFE_MANAGER)
    entry = _get_entry_under(cafe_id, schedule_id, entry_id)
    require_cafe_owner(cafe_id)
    if entry["status"] != "BAKING":
        raise ApiError("ERR_INVALID_STATE", "Only a BAKING entry may be completed.")
    entry["status"] = "COMPLETED"
    db.touch(entry)
    return resp.object_response(resp.serialize(entry), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/schedules/<schedule_id>/entries/<entry_id>/discard",
          methods=["POST"])
def discard_bake_entry(cafe_id, schedule_id, entry_id):
    authorize(ROLE_CAFE_MANAGER)
    entry = _get_entry_under(cafe_id, schedule_id, entry_id)
    require_cafe_owner(cafe_id)
    if entry["status"] not in ("PROOFING", "BAKING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PROOFING or BAKING entry may be discarded.")
    entry["status"] = "DISCARDED"
    db.touch(entry)
    return resp.object_response(resp.serialize(entry), 200)
