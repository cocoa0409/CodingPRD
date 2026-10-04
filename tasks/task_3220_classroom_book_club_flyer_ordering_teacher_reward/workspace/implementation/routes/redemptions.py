"""Redemption endpoints."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles, current_user_id
from response import object_response
from services import (
    new_record, touch, serialize_redemption, school_posture, title_license_status,
    accrue_royalty, append_ledger, SUPPLY_UNIT_POINTS_COST,
)
from routes.common import get_body, path_get, ref_get, req_field, req_int, req_enum

bp = Blueprint("redemptions", __name__)


@bp.post("/club/redemptions")
@require_roles("Teacher")
def create_redemption():
    body = get_body()
    teacher_id = req_field(body, "teacher_id")
    kind = req_enum(body, "kind", {"BOOK", "SUPPLY"})
    title_id = body.get("title_id")
    qty = req_int(body, "qty")
    ref_get(db.teachers, teacher_id, "Teacher")
    if qty < 1:
        raise_err("ERR_INVALID_REQUEST", "qty must be >= 1")
    if kind == "BOOK":
        if title_id is None:
            raise_err("ERR_REDEMPTION_SHAPE_INVALID", "kind BOOK requires title_id")
        title = ref_get(db.titles, title_id, "Title")
        points_cost = qty * title["points_cost"]
    else:
        if title_id is not None:
            raise_err("ERR_REDEMPTION_SHAPE_INVALID", "kind SUPPLY forbids title_id")
        points_cost = qty * SUPPLY_UNIT_POINTS_COST
    redemption = new_record({
        "teacher_id": teacher_id,
        "kind": kind,
        "title_id": title_id,
        "qty": qty,
        "points_cost": points_cost,
        "status": "PENDING",
    })
    db.redemptions[redemption["id"]] = redemption
    return object_response(serialize_redemption(redemption), 201)


@bp.get("/club/redemptions/<rid>")
@require_roles("ClubAdmin", "Teacher")
def get_redemption(rid):
    return object_response(serialize_redemption(path_get(db.redemptions, rid, "Redemption")))


@bp.post("/club/redemptions/<rid>/confirm")
@require_roles("Teacher")
def confirm_redemption(rid):
    redemption = path_get(db.redemptions, rid, "Redemption")
    if redemption["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "Redemption is CANCELLED")
    if redemption["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Confirm requires status PENDING")
    teacher = db.teachers[redemption["teacher_id"]]
    if school_posture(teacher["school_id"]) != "NORMAL":
        raise_err("ERR_SCHOOL_RESTRICTED", "School posture is RESTRICTED")
    title = None
    if redemption["kind"] == "BOOK":
        title = db.titles.get(redemption["title_id"])
        if title is not None and title_license_status(title) != "ACTIVE":
            raise_err("ERR_LICENSE_SUSPENDED", "Title license is SUSPENDED")
    if teacher["points_balance"] < redemption["points_cost"]:
        raise_err("ERR_INSUFFICIENT_POINTS", "Teacher.points_balance below redemption points_cost")
    if current_user_id() != redemption["teacher_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Acting teacher is not the redemption's teacher")
    cost = redemption["points_cost"]
    teacher["points_balance"] -= cost
    teacher["points_redeemed_total"] += cost
    touch(teacher)
    append_ledger(teacher["id"], "REDEEM", -cost, "REDEMPTION", redemption["id"])
    if title is not None:
        accrue_royalty(title, redemption["qty"])
    redemption["status"] = "CONFIRMED"
    touch(redemption)
    return object_response(serialize_redemption(redemption))


@bp.post("/club/redemptions/<rid>/cancel")
@require_roles("Teacher")
def cancel_redemption(rid):
    redemption = path_get(db.redemptions, rid, "Redemption")
    if redemption["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "Redemption is CANCELLED")
    if redemption["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Cancel requires status PENDING")
    if current_user_id() != redemption["teacher_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Acting teacher is not the redemption's teacher")
    redemption["status"] = "CANCELLED"
    touch(redemption)
    return object_response(serialize_redemption(redemption))
