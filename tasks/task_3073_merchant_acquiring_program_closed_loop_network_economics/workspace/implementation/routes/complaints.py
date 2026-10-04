"""Acceptance complaints and the suppression feedback loop."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from errors import ERR_INVALID_STATE, ApiError
from paging import filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import gap_engine
from validation import body_object, require_enum, require_string

bp = Blueprint("complaints", __name__)

COMPLAINT_TYPES = (
    "MERCHANT_NOT_ACCEPTED",
    "STAFF_ATTITUDE",
    "TERMINAL_TECHNICAL",
    "PRICING_SURCHARGE",
)
COMPLAINT_STATUSES = ("FILED", "UNDER_REVIEW", "UPHELD", "DISMISSED")

SERVICE = ["NetworkService"]


@bp.post("/complaints")
def file_complaint():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["CardMember", "NetworkService"])
    body = body_object(request.get_json(silent=True) or {},
                       {"merchant_id", "cardmember_id", "complaint_type"})
    merchant_id = require_string(body, "merchant_id")
    cardmember_id = require_string(body, "cardmember_id")
    complaint_type = require_enum(body, "complaint_type", COMPLAINT_TYPES)

    _common.merchant(merchant_id)
    member = _common.cardmember(cardmember_id)
    if caller.role == "CardMember":
        require_owned_by_caller(caller, member["id"])

    with STORE.lock:
        complaint_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": complaint_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "merchant_id": merchant_id,
            "cardmember_id": cardmember_id,
            "complaint_type": complaint_type,
            "complaint_status": "FILED",
        }
        STORE.acceptance_complaints[complaint_id] = row
    return ok_object(_common.render(row)), 201


@bp.get("/complaints/<complaint_id>")
def get_complaint(complaint_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    row = _common.complaint(complaint_id)
    return ok_object(_common.render(row))


@bp.get("/complaints")
def list_complaints():
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    cardmember_id = filter_arg(request.args, "cardmember_id")
    complaint_status = filter_arg(request.args, "complaint_status", COMPLAINT_STATUSES)

    rows = list(STORE.acceptance_complaints.values())
    if merchant_id is not None:
        rows = [row for row in rows if row["merchant_id"] == merchant_id]
    if cardmember_id is not None:
        rows = [row for row in rows if row["cardmember_id"] == cardmember_id]
    if complaint_status is not None:
        rows = [row for row in rows if row["complaint_status"] == complaint_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/complaints/<complaint_id>/take-up")
def take_up(complaint_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.complaint(complaint_id)
    with STORE.lock:
        if row["complaint_status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE)
        row["complaint_status"] = "UNDER_REVIEW"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/complaints/<complaint_id>/uphold")
def uphold(complaint_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.complaint(complaint_id)
    with STORE.lock:
        if row["complaint_status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE)
        # Priority 10: a merchant already enrolled as PROSPECT is refused.
        gap_engine.uphold_complaint_gap(STORE, row)
        row["complaint_status"] = "UPHELD"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/complaints/<complaint_id>/dismiss")
def dismiss(complaint_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.complaint(complaint_id)
    with STORE.lock:
        if row["complaint_status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE)
        row["complaint_status"] = "DISMISSED"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))


@bp.post("/complaints/<complaint_id>/reopen")
def reopen(complaint_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, SERVICE)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.complaint(complaint_id)
    with STORE.lock:
        if row["complaint_status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE)
        row["complaint_status"] = "FILED"
        row["version"] = row["version"] + 1
        row["updated_at"] = STORE.clock.now()
    return ok_object(_common.render(row))