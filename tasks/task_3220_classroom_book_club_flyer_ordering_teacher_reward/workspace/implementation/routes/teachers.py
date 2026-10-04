"""Teacher endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import (
    new_record, serialize_teacher, serialize_ledger, serialize_order,
    serialize_redemption, serialize_donation, GRADE_BANDS,
)
from routes.common import get_body, path_get, ref_get, req_field, req_enum

bp = Blueprint("teachers", __name__)


@bp.post("/club/teachers")
@require_roles("ClubAdmin", "SchoolAdmin")
def create_teacher():
    body = get_body()
    school_id = req_field(body, "school_id")
    ref_get(db.schools, school_id, "School")
    full_name = req_field(body, "full_name")
    email = req_field(body, "email")
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    if not isinstance(full_name, str) or not isinstance(email, str):
        raise_err("ERR_INVALID_REQUEST", "full_name and email must be strings")
    for t in db.teachers.values():
        if t["email"] == email:
            raise_err("ERR_INVALID_REQUEST", "email must be unique across all teachers")
    teacher = new_record({
        "school_id": school_id,
        "full_name": full_name,
        "email": email,
        "grade_band": grade_band,
        "points_balance": 0,
        "points_earned_total": 0,
        "points_redeemed_total": 0,
        "points_expired_total": 0,
        "donated_books_received": 0,
    })
    db.teachers[teacher["id"]] = teacher
    return object_response(serialize_teacher(teacher), 201)


@bp.get("/club/teachers")
@require_roles("ClubAdmin", "SchoolAdmin")
def list_teachers():
    items = list(db.teachers.values())
    sid = request.args.get("school_id")
    if sid:
        items = [t for t in items if t["school_id"] == sid]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_teacher(t) for t in page], total, limit, offset))


@bp.get("/club/teachers/<tid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def get_teacher(tid):
    return object_response(serialize_teacher(path_get(db.teachers, tid, "Teacher")))


@bp.get("/club/teachers/<tid>/points-ledger")
@require_roles("ClubAdmin", "Teacher")
def teacher_ledger(tid):
    path_get(db.teachers, tid, "Teacher")
    items = [e for e in db.ledger.values() if e["teacher_id"] == tid]
    et = request.args.get("entry_type")
    if et:
        items = [e for e in items if e["entry_type"] == et]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_ledger(e) for e in page], total, limit, offset))


@bp.get("/club/teachers/<tid>/class-orders")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def teacher_orders(tid):
    path_get(db.teachers, tid, "Teacher")
    items = [o for o in db.class_orders.values() if o["teacher_id"] == tid]
    st = request.args.get("status")
    if st:
        items = [o for o in items if o["status"] == st]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_order(o) for o in page], total, limit, offset))


@bp.get("/club/teachers/<tid>/redemptions")
@require_roles("ClubAdmin", "Teacher")
def teacher_redemptions(tid):
    path_get(db.teachers, tid, "Teacher")
    items = [r for r in db.redemptions.values() if r["teacher_id"] == tid]
    st = request.args.get("status")
    if st:
        items = [r for r in items if r["status"] == st]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_redemption(r) for r in page], total, limit, offset))


@bp.get("/club/teachers/<tid>/donation-requests")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Donor")
def teacher_donations(tid):
    path_get(db.teachers, tid, "Teacher")
    items = sorted((d for d in db.donation_requests.values() if d["teacher_id"] == tid),
                   key=lambda d: (d["created_at"], d["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_donation(d) for d in page], total, limit, offset))
