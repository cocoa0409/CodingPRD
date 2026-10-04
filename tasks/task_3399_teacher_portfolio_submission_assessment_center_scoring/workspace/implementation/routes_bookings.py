"""Assessment booking endpoints (PRD 3.4): create, read, list, transition
(cancel / complete / no-show)."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import domain
import errors as E
import serializers as ser
from response import ok, ok_list
from store import DB, new_id, stamp_new, touch, now
from validation import (auth_headers, require_role, body, req_field,
                        parse_dt_field, pagination_params, paginate,
                        validate_score_value)

bp = Blueprint("bookings", __name__)


def _get_booking_or_404(booking_id):
    booking = DB.bookings.get(booking_id)
    if booking is None:
        E.fail(E.ERR_BOOKING_NOT_FOUND, 404, "Booking not found: %s" % booking_id)
    return booking


@bp.post("/bookings")
def create_booking():
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    data = body()
    center_id = req_field(data, "center_id")
    cycle_id = req_field(data, "cycle_id")
    slot_start = parse_dt_field(req_field(data, "slot_start_at"), "slot_start_at")
    center = DB.centers.get(center_id)
    if center is None:
        E.fail(E.ERR_CENTER_NOT_FOUND, 404, "Center not found: %s" % center_id)
    cycle = DB.cycles.get(cycle_id)
    if cycle is None:
        E.fail(E.ERR_CYCLE_NOT_FOUND, 404, "Cycle not found: %s" % cycle_id)
    candidate = DB.candidates.get(uid)
    if candidate is None:
        E.fail(E.ERR_CANDIDATE_NOT_FOUND, 404, "Candidate not found: %s" % uid)
    # PRD 3.4 gate order: eligible -> open ASSESSMENT attempt -> temporal ->
    # active booking -> capacity.
    if candidate["status"] != "ELIGIBLE":
        E.fail(E.ERR_CANDIDATE_NOT_ELIGIBLE, 409,
               "Only an ELIGIBLE candidate may book an assessment session")
    open_attempts = [s for s in DB.submissions.values()
                     if s["candidate_id"] == uid
                     and s["cycle_id"] == cycle_id
                     and s["kind"] == "ASSESSMENT"
                     and s["status"] == "IN_PROGRESS"]
    if not open_attempts:
        E.fail(E.ERR_SUBMISSION_NOT_FOUND, 404,
               "No open ASSESSMENT attempt exists for this candidate and cycle")
    if not slot_start > now():
        E.fail(E.ERR_SLOT_IN_PAST, 422,
               "slot_start_at must be strictly after the logical clock")
    if slot_start > cycle["submission_window_close"]:
        E.fail(E.ERR_SLOT_OUTSIDE_WINDOW, 422,
               "slot_start_at must be no later than submission_window_close")
    if any(b for b in DB.bookings.values()
           if b["candidate_id"] == uid and b["cycle_id"] == cycle_id
           and b["status"] == "BOOKED"):
        E.fail(E.ERR_ACTIVE_BOOKING_EXISTS, 409,
               "Candidate already holds a BOOKED booking in this cycle")
    occupied = sum(1 for b in DB.bookings.values()
                   if b["center_id"] == center_id
                   and b["slot_start_at"] == slot_start
                   and b["status"] == "BOOKED")
    if occupied >= center["slot_capacity"]:
        E.fail(E.ERR_SLOT_CAPACITY_FULL, 409,
               "No seats remain for this center at this slot start")
    booking = {
        "id": new_id(),
        "candidate_id": uid,
        "center_id": center_id,
        "cycle_id": cycle_id,
        "slot_start_at": slot_start,
        "slot_end_at": slot_start + timedelta(minutes=C.SESSION_DURATION_MINUTES),
        "status": "BOOKED",
        "earned_score": None,
    }
    stamp_new(booking)
    DB.bookings[booking["id"]] = booking
    return ok(ser.booking(booking), 201)


@bp.get("/bookings/<booking_id>")
def get_booking(booking_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    booking = _get_booking_or_404(booking_id)
    if role == C.ROLE_CANDIDATE and booking["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own bookings")
    return ok(ser.booking(booking))


@bp.get("/bookings")
def list_bookings():
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN, C.ROLE_BOARD_ADMIN])
    limit, offset = pagination_params()
    items = list(DB.bookings.values())
    candidate_id = request.args.get("candidate_id")
    if candidate_id is not None:
        items = [b for b in items if b["candidate_id"] == candidate_id]
    center_id = request.args.get("center_id")
    if center_id is not None:
        items = [b for b in items if b["center_id"] == center_id]
    cycle_id = request.args.get("cycle_id")
    if cycle_id is not None:
        items = [b for b in items if b["cycle_id"] == cycle_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.booking(b) for b in page], limit, offset, total)


@bp.post("/bookings/<booking_id>/transition")
def transition_booking(booking_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN])
    data = body()
    target = req_field(data, "to")
    booking = _get_booking_or_404(booking_id)
    if target == "CANCELLED":
        # Only the owning candidate may cancel (PRD 3.4).
        if role != C.ROLE_CANDIDATE or uid != booking["candidate_id"]:
            E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
                   "Only the owning candidate may cancel a booking")
    elif target in ("COMPLETED", "NO_SHOW"):
        if role != C.ROLE_SCORING_ADMIN:
            E.fail(E.ERR_INSUFFICIENT_PERMISSIONS, 403,
                   "Only a ScoringAdministrator may mark %s" % target)
    else:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "to must be one of CANCELLED, COMPLETED, NO_SHOW")
    if booking["status"] != "BOOKED":
        E.fail(E.ERR_BOOKING_NOT_TRANSITIONABLE, 409,
               "Booking in %s cannot transition" % booking["status"])
    if target == "CANCELLED":
        booking["status"] = "CANCELLED"
    elif target == "NO_SHOW":
        booking["status"] = "NO_SHOW"
    else:  # COMPLETED
        if now() < booking["slot_start_at"]:
            E.fail(E.ERR_BOOKING_NOT_COMPLETABLE, 409,
                   "A session cannot complete before its slot_start_at")
        if "earned_score" not in data or data["earned_score"] is None:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "earned_score is required for COMPLETED")
        booking["earned_score"] = validate_score_value(
            data["earned_score"], "earned_score")
        booking["status"] = "COMPLETED"
        touch(booking)
        domain.on_booking_completed(booking)
        return ok(ser.booking(booking))
    touch(booking)
    return ok(ser.booking(booking))
