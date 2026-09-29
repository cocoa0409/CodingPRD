"""Shift settlement batches and the recount cycle."""
from flask import Blueprint

import db
import response
import shapes
from constants import PREFIX, TENDER_TYPES
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, NIGHT_AUDITOR, OUTLET_MANAGER,
                        REVENUE_MANAGER, authenticate)
from money import q2
from services import derive, lookup, serial

bp = Blueprint("batches", __name__, url_prefix=PREFIX)


def _require_scope(role, user_id, outlet_id):
    if role == OUTLET_MANAGER and user_id != outlet_id:
        raise ApiError("ERR_OUTLET_SCOPE_VIOLATION",
                       "An outlet manager may only act on their own outlet.")


def _check_overlap(batch_id, outlet_id, business_date_id, tender_type, start, end):
    """Half-open windows: touching shifts do not overlap."""
    for row in db.all_of("batches"):
        if row["id"] == batch_id:
            continue
        if row["outlet_id"] != outlet_id or row["business_date_id"] != business_date_id:
            continue
        if row["tender_type"] != tender_type:
            continue
        if row["status"] == "RECOUNT_REQUESTED":
            continue
        if start < row["shift_end_at"] and row["shift_start_at"] < end:
            raise ApiError("ERR_SHIFT_WINDOW_OVERLAP",
                           "Another batch already claims part of that window.")


@bp.route("/settlement-batches", methods=["POST"])
def create_batch():
    user_id, role = authenticate([OUTLET_MANAGER, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("outlet_id", "string", required=True),
        shapes.Field("tender_type", "string", required=True, enum=TENDER_TYPES),
        shapes.Field("shift_start_at", "instant", required=True),
        shapes.Field("shift_end_at", "instant", required=True),
        shapes.Field("declared_amount", "number", required=True, ge=0),
    ])
    date_row = lookup.get_date(body["business_date_id"])
    outlet = lookup.get_outlet(body["outlet_id"])
    lookup.require_not_archived(date_row)
    _require_scope(role, user_id, outlet["id"])
    if outlet["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The outlet belongs to a different property.")
    if not body["shift_start_at"] < body["shift_end_at"]:
        raise ApiError("ERR_SHIFT_WINDOW_INVALID",
                       "shift_start_at must precede shift_end_at.")
    _check_overlap(None, outlet["id"], date_row["id"], body["tender_type"],
                   body["shift_start_at"], body["shift_end_at"])
    if outlet["status"] == "SUSPENDED":
        raise ApiError("ERR_OUTLET_SUSPENDED", "The outlet is suspended.")
    row = db.insert("batches", {
        "_kind": "SettlementBatch",
        "business_date_id": date_row["id"],
        "outlet_id": outlet["id"],
        "tender_type": body["tender_type"],
        "shift_start_at": body["shift_start_at"],
        "shift_end_at": body["shift_end_at"],
        "declared_amount": q2(body["declared_amount"]),
        "system_amount": None,
        "variance_amount": None,
        "status": "DECLARED",
        "recount_round": 0,
        "declared_by_user_id": user_id,
        "accepted_by_user_id": None,
    })
    return response.created(serial.batch_out(row))


@bp.route("/settlement-batches/<row_id>/request-recount", methods=["POST"])
def request_recount(row_id):
    authenticate([NIGHT_AUDITOR])
    batch = lookup.get_batch(row_id)
    lookup.require_not_archived(lookup.get_date(batch["business_date_id"]))
    if batch["status"] != "VARIANCE_FLAGGED":
        raise ApiError("ERR_BATCH_NOT_FLAGGED", "The batch is not flagged.")
    if int(batch["recount_round"]) >= 2:
        raise ApiError("ERR_RECOUNT_LIMIT_REACHED",
                       "The batch has exhausted its recount rounds.")
    batch["status"] = "RECOUNT_REQUESTED"
    batch["recount_round"] = int(batch["recount_round"]) + 1
    derive.touch(batch)
    return response.ok(serial.batch_out(batch))


@bp.route("/settlement-batches/<row_id>/redeclare", methods=["POST"])
def redeclare(row_id):
    user_id, role = authenticate([OUTLET_MANAGER, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("declared_amount", "number", required=True, ge=0),
        shapes.Field("shift_start_at", "instant"),
        shapes.Field("shift_end_at", "instant"),
    ])
    batch = lookup.get_batch(row_id)
    lookup.require_not_archived(lookup.get_date(batch["business_date_id"]))
    if batch["status"] != "RECOUNT_REQUESTED":
        raise ApiError("ERR_BATCH_NOT_AWAITING_RECOUNT",
                       "The batch is not awaiting a recount.")
    _require_scope(role, user_id, batch["outlet_id"])
    start = body["shift_start_at"] or batch["shift_start_at"]
    end = body["shift_end_at"] or batch["shift_end_at"]
    if not start < end:
        raise ApiError("ERR_SHIFT_WINDOW_INVALID",
                       "shift_start_at must precede shift_end_at.")
    _check_overlap(batch["id"], batch["outlet_id"], batch["business_date_id"],
                   batch["tender_type"], start, end)
    batch["shift_start_at"] = start
    batch["shift_end_at"] = end
    batch["declared_amount"] = q2(body["declared_amount"])
    batch["variance_amount"] = None
    batch["status"] = "DECLARED"
    batch["declared_by_user_id"] = user_id
    derive.touch(batch)
    return response.ok(serial.batch_out(batch))


@bp.route("/settlement-batches/<row_id>/accept-variance", methods=["POST"])
def accept_variance(row_id):
    user_id, _role = authenticate([REVENUE_MANAGER, CONTROLLER])
    batch = lookup.get_batch(row_id)
    lookup.require_not_archived(lookup.get_date(batch["business_date_id"]))
    if batch["status"] != "VARIANCE_FLAGGED":
        raise ApiError("ERR_BATCH_NOT_FLAGGED", "The batch is not flagged.")
    if batch["declared_by_user_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "The declaring operator may not accept their own variance.")
    batch["status"] = "ACCEPTED_WITH_VARIANCE"
    batch["accepted_by_user_id"] = user_id
    derive.touch(batch)
    return response.ok(serial.batch_out(batch))


@bp.route("/settlement-batches/<row_id>", methods=["GET"])
def get_batch(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.batch_out(lookup.get_batch(row_id)))


@bp.route("/settlement-batches", methods=["GET"])
def list_batches():
    authenticate(ALL_ROLES)
    rows = db.all_of("batches")
    for key in ("business_date_id", "outlet_id", "status", "tender_type"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.batch_out)
    return response.collection(items, meta)
