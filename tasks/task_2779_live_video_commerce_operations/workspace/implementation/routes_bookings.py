"""Host bookings and disclosure obligations (PRD 3.1)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_HOST, ROLE_SHOW_PRODUCER, authenticate, body, fk_id,
    get_booking, get_disclosure, get_host, get_show, pagination, req_dt,
    req_enum, req_int, req_str, slice_rows,
)
from store import by_created, db, new_record, now, touch

bp = Blueprint("bookings", __name__)

BUFFER = timedelta(minutes=calc.HOST_TURNAROUND_BUFFER_MIN)


# ------------------------------------------------------------- host bookings
@bp.post("/host-bookings")
def create_booking():
    authenticate([ROLE_SHOW_PRODUCER])
    payload = body()
    show = get_show(fk_id(payload, "show_id"))
    host = get_host(fk_id(payload, "host_id"))
    role = req_enum(payload, "role", ("PRIMARY", "GUEST"))
    call_time_at = req_dt(payload, "call_time_at")
    release_time_at = req_dt(payload, "release_time_at")
    if not release_time_at > call_time_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "release_time_at must be strictly after call_time_at.")
    fee_cents = req_int(payload, "fee_cents", 0)
    if show["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    # Rung 14 — the half-open interval expanded by the turnaround buffer on both
    # sides, over this host's PENDING and CONFIRMED bookings.
    for existing in by_created(list(db.bookings.values())):
        if existing["host_id"] != host["id"]:
            continue
        if existing["status"] not in ("PENDING", "CONFIRMED"):
            continue
        if (call_time_at < existing["release_time_at"] + BUFFER
                and existing["call_time_at"] < release_time_at + BUFFER):
            raise ApiError("ERR_HOST_BOOKING_OVERLAP")
    # Rung 20 — a show carries at most one lead presenter.
    if role == "PRIMARY":
        for existing in calc.bookings_of(show["id"]):
            if existing["role"] == "PRIMARY" and existing["status"] in ("PENDING", "CONFIRMED"):
                raise ApiError("ERR_PRIMARY_HOST_CONFLICT")
    record = new_record()
    record.update({
        "show_id": show["id"],
        "host_id": host["id"],
        "role": role,
        "status": "PENDING",
        "call_time_at": call_time_at,
        "release_time_at": release_time_at,
        "fee_cents": fee_cents,
        "confirmed_at": None,
        "cancel_reason": None,
    })
    db.bookings[record["id"]] = record
    return respond(ser.booking_out(record), 201)


@bp.get("/host-bookings/<booking_id>")
def read_booking(booking_id):
    authenticate(ALL_ROLES)
    return respond(ser.booking_out(get_booking(booking_id)))


@bp.get("/host-bookings")
def list_bookings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.bookings.values())
    for field in ("show_id", "host_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.booking_out(r) for r in page], limit, offset, total)


@bp.post("/host-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    user_id, _ = authenticate([ROLE_HOST])
    booking = get_booking(booking_id)
    if booking["host_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if booking["status"] != "PENDING":
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    show = db.shows.get(booking["show_id"])
    if show is None or show["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    host = db.hosts.get(booking["host_id"])
    if host is None or calc.certification_status(host) != "CERTIFIED":
        raise ApiError("ERR_HOST_CERTIFICATION_EXPIRED")
    booking["status"] = "CONFIRMED"
    booking["confirmed_at"] = now()
    touch(booking)
    return respond(ser.booking_out(booking))


@bp.post("/host-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = authenticate([ROLE_SHOW_PRODUCER, ROLE_HOST])
    booking = get_booking(booking_id)
    if role == ROLE_HOST and booking["host_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    cancel_reason = req_str(payload, "cancel_reason")
    if booking["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    show = db.shows.get(booking["show_id"])
    if show is None or show["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    was_confirmed = booking["status"] == "CONFIRMED"
    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = cancel_reason
    touch(booking)
    # Void the paperwork attached to this booking.
    for record in by_created(list(db.disclosures.values())):
        if record["host_booking_id"] != booking["id"]:
            continue
        if record["status"] != "PENDING":
            continue
        record["status"] = "VOIDED"
        touch(record)
    if was_confirmed and booking["role"] == "PRIMARY" and show["status"] == "READY":
        calc.revert_show_to_draft(show)
    return respond(ser.booking_out(booking))


# -------------------------------------------------------- disclosure records
@bp.post("/disclosure-records")
def create_disclosure():
    authenticate([ROLE_SHOW_PRODUCER])
    payload = body()
    show = get_show(fk_id(payload, "show_id"))
    booking = get_booking(fk_id(payload, "host_booking_id"))
    disclosure_type = req_enum(
        payload, "disclosure_type",
        ("PAID_ENDORSEMENT", "MATERIAL_CONNECTION", "FREE_PRODUCT"))
    required_script_code = req_str(payload, "required_script_code")
    if booking["show_id"] != show["id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "host_booking_id belongs to a different show than show_id.")
    if show["status"] not in ("DRAFT", "READY", "LIVE"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    record = new_record()
    record.update({
        "show_id": show["id"],
        "host_booking_id": booking["id"],
        "disclosure_type": disclosure_type,
        "required_script_code": required_script_code,
        "status": "PENDING",
        "acknowledged_at": None,
        "acknowledged_late": False,
    })
    db.disclosures[record["id"]] = record
    return respond(ser.disclosure_out(record), 201)


@bp.get("/disclosure-records/<record_id>")
def read_disclosure(record_id):
    authenticate(ALL_ROLES)
    return respond(ser.disclosure_out(get_disclosure(record_id)))


@bp.get("/disclosure-records")
def list_disclosures():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.disclosures.values())
    for field in ("show_id", "host_booking_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.disclosure_out(r) for r in page], limit, offset, total)


@bp.post("/disclosure-records/<record_id>/acknowledge")
def acknowledge_disclosure(record_id):
    user_id, _ = authenticate([ROLE_HOST])
    record = get_disclosure(record_id)
    booking = db.bookings.get(record["host_booking_id"])
    if booking is None or booking["host_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    script_code_spoken = req_str(payload, "script_code_spoken")
    if script_code_spoken != record["required_script_code"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "script_code_spoken must equal the record's required_script_code.")
    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_DISCLOSURE_STATE")
    if booking["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    show = db.shows.get(record["show_id"])
    if show is None or show["status"] not in ("DRAFT", "READY", "LIVE"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    stamp = now()
    record["status"] = "ACKNOWLEDGED"
    record["acknowledged_at"] = stamp
    went_live_at = show["went_live_at"]
    record["acknowledged_late"] = bool(went_live_at is not None and stamp > went_live_at)
    touch(record)
    return respond(ser.disclosure_out(record))
