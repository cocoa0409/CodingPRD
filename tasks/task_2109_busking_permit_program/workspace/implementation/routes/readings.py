"""Noise metering and the compliance escalation (PRD section 3.8)."""
from flask import Blueprint, request

import db
from body import Body
from gates import (P_BODY, P_BODY_FK, P_OWNER, P_PATH, P_READING_WINDOW,
                   resolve, resolve_body_fk, run_gates)
from errors import raise_err
from listing import paged
from middleware import (NOISE_INSPECTOR, PERFORMER, PERMIT_OFFICER,
                        require_owner, require_roles)
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, sort_created, touch

bp = Blueprint("readings", __name__, url_prefix="/busking")


@bp.post("/noise-readings")
def file_reading():
    user_id, _role = require_roles([NOISE_INSPECTOR])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        ctx["booking"] = resolve_body_fk("bookings", raw, "booking_id")

    def check_body():
        body.req_id("booking_id")
        ctx["taken_at"] = body.req_dt("taken_at")
        ctx["reading_db"] = body.req_int("reading_db", 0, 140)

    def check_window():
        booking = ctx["booking"]
        if not (booking["start_at"] <= ctx["taken_at"] < booking["end_at"]):
            raise_err("ERR_READING_OUTSIDE_SESSION",
                      "The measurement instant is outside the session window")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_BODY, check_body),
        (P_READING_WINDOW, check_window),
    ])

    booking = ctx["booking"]
    permit = db.get("permits", booking["permit_id"])
    pitch = db.get("pitches", booking["pitch_id"])
    zone = db.get("zones", pitch["zone_id"])
    cap = calc.effective_noise_cap(
        zone, pitch, booking["amplification_planned"],
        permit["compliance_status"], ctx["taken_at"])
    verdict = "COMPLIANT" if ctx["reading_db"] <= cap else "VIOLATION"

    reading = new_entity("readings", {
        "booking_id": booking["id"],
        "inspector_user_id": user_id,
        "taken_at": ctx["taken_at"],
        "reading_db": ctx["reading_db"],
        "effective_cap_db": cap,
        "verdict": verdict,
    }, common_fields=False)

    if verdict == "VIOLATION":
        booking["noise_violation_count"] += 1
        touch(booking)
        permit["noise_violation_count"] += 1
        count = permit["noise_violation_count"]
        if (permit["compliance_status"] == "CLEAR"
                and count == calc.NOISE_VIOLATIONS_FOR_WARNING):
            permit["compliance_status"] = "WARNED"
            touch(permit)
        elif (permit["compliance_status"] == "WARNED"
              and count >= calc.NOISE_VIOLATIONS_FOR_SUSPENSION):
            domain.suspend_permit(permit)
        else:
            touch(permit)
    return ok_object(serialize(reading), status=201)


@bp.get("/session-bookings/<booking_id>/noise-readings")
def list_readings(booking_id):
    user_id, role = require_roles([PERMIT_OFFICER, NOISE_INSPECTOR, PERFORMER])
    ctx = {}

    def resolve_booking():
        ctx["booking"] = resolve("bookings", booking_id)
        ctx["permit"] = db.get("permits", ctx["booking"]["permit_id"])

    run_gates([
        (P_PATH, resolve_booking),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
    ])

    rows = sort_created([r for r in db.all_of("readings")
                         if r["booking_id"] == ctx["booking"]["id"]])
    verdict = request.args.get("verdict")
    if verdict is not None:
        rows = [row for row in rows if row["verdict"] == verdict]
    return paged(rows, request.args)
