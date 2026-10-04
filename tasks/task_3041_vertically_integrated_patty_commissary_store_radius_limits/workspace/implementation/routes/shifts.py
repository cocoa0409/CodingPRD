"""ShiftAssignment routes."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_POSTURE_BLOCKS,
    ERR_SHIFT_INVALID_STATE,
    ERR_SHIFT_OVERLAP,
    conflict,
    forbidden,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    parse_datetime,
    req_field,
    req_string,
    touch,
)

bp = Blueprint("shifts", __name__)


def _check_manager_scope(user_id, role, store):
    """StoreManager may only schedule at their own store; HRDirector anywhere."""
    if role == "StoreManager" and user_id != store.get("manager_associate_id"):
        raise forbidden("StoreManager may only schedule at their own store")


@bp.route("/stores/<sid>/shifts", methods=["POST"])
def create_shift(sid):
    user_id, role = require_roles("StoreManager", "HRDirector")
    store = domain.get_store(sid)
    body = get_json_body()
    associate_id = req_string(body, "associate_id")
    shift_start = parse_datetime(req_field(body, "shift_start"), "shift_start")
    shift_end = parse_datetime(req_field(body, "shift_end"), "shift_end")
    if shift_end <= shift_start:
        raise invalid_request("shift_end must be after shift_start")
    # Body FK existence (tier 5).
    domain.get_associate(associate_id)
    # Identity/scope (tier 3).
    _check_manager_scope(user_id, role, store)
    # Overlap (tier 15): half-open [start, end) intervals of the same associate.
    for s in db.shifts.values():
        if (
            s["associate_id"] == associate_id
            and s["status"] == "SCHEDULED"
            and s["shift_start"] < shift_end
            and shift_start < s["shift_end"]
        ):
            raise unprocessable(ERR_SHIFT_OVERLAP, "Shift overlaps an existing SCHEDULED shift")
    # Posture gate (tier 22): CRITICAL blocks; during OPENING_SURGE STRAINED also
    # blocks. Shifts entirely in the past are irrelevant to current staffing and
    # bypass the gate; otherwise the candidate shift counts toward coverage when
    # its window contains the clock.
    if shift_end > db.clock_now():
        candidate_covers_now = shift_start <= db.clock_now() < shift_end
        posture = calc.staffing_posture(store["id"], extra_covering_shifts=1 if candidate_covers_now else 0)
        if posture == "CRITICAL":
            raise unprocessable(ERR_POSTURE_BLOCKS, "Staffing posture CRITICAL blocks scheduling")
        if store.get("opening_mode") == "OPENING_SURGE" and posture == "STRAINED":
            raise unprocessable(ERR_POSTURE_BLOCKS, "Staffing posture STRAINED blocks scheduling during OPENING_SURGE")
    s = base_entity()
    s.update({
        "store_id": store["id"],
        "associate_id": associate_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "status": "SCHEDULED",
    })
    db.shifts[s["id"]] = s
    return success_object(domain.ser_shift(s), 201)


@bp.route("/stores/<sid>/shifts", methods=["GET"])
def list_store_shifts(sid):
    require_roles("StoreManager", "HRDirector")
    store = domain.get_store(sid)
    items = [s for s in db.shifts.values() if s["store_id"] == store["id"]]
    aid = request.args.get("associate_id")
    if aid is not None:
        items = [s for s in items if s["associate_id"] == aid]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_shift(s) for s in page], limit, offset, total)


@bp.route("/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_roles("StoreManager", "HRDirector")
    return success_object(domain.ser_shift(domain.get_shift(sid)))


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    require_roles("StoreManager", "HRDirector")
    items = list(db.shifts.values())
    aid = request.args.get("associate_id")
    if aid is not None:
        items = [s for s in items if s["associate_id"] == aid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [s for s in items if s["store_id"] == sid]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_shift(s) for s in page], limit, offset, total)


@bp.route("/shifts/<sid>/cancel", methods=["POST"])
def cancel_shift(sid):
    user_id, _ = require_roles("StoreManager")
    shift = domain.get_shift(sid)
    store = db.stores.get(shift["store_id"])
    # Identity (tier 3): manager of the shift's store only.
    if store is None or user_id != store.get("manager_associate_id"):
        raise forbidden("StoreManager may only cancel shifts at their own store")
    if shift["status"] != "SCHEDULED":
        raise conflict(ERR_SHIFT_INVALID_STATE, "Shift is not SCHEDULED")
    shift["status"] = "CANCELLED"
    touch(shift)
    return success_object(domain.ser_shift(shift))
