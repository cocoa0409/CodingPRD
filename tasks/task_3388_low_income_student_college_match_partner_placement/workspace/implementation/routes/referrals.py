"""Referral endpoints: nominate, revoke, list, get."""
from flask import Blueprint, request

import serializers
import store
from auth import forbid, identity, require_roles
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_WRONG_CYCLE_PHASE
from response import ok_object, paginated
from validation import KIND_STR, get_body, validate

bp = Blueprint("referrals", __name__)

LIST_ROLES = ("ProgramAdmin", "Counselor", "PartnerStaff", "Student")


def get_referral_or_404(referral_id):
    referral = store.referrals.get(referral_id)
    if referral is None:
        raise ApiError(ERR_NOT_FOUND, "referral not found")
    return referral


def check_referral_ownership(role, uid, referral):
    """Counselor: own referrals (counselor_id). PartnerStaff: own referrals
    (partner_id). Student: referrals naming them. ProgramAdmin: any."""
    if role == "Counselor" and referral["counselor_id"] != uid:
        forbid("a counselor may only act on their own referrals")
    if role == "PartnerStaff" and referral["partner_id"] != uid:
        forbid("partner staff may only act on their own referrals")
    if role == "Student" and referral["student_id"] != uid:
        forbid("a student may only view referrals naming them")


@bp.post("/referrals")
def create_referral():
    body = get_body()
    values = validate(body, [
        ("student_id", KIND_STR, True, None, None),
        ("cycle_id", KIND_STR, True, None, None),
        ("note", KIND_STR, False, "", None),
    ])
    role, uid = identity()
    require_roles(role, ("Counselor", "PartnerStaff"))
    cycle = store.cycles.get(values["cycle_id"])
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, "cycle not found")
    # Referral nominations are permitted only in RECRUITMENT or APPLICATION_OPEN.
    if cycle["phase"] not in ("RECRUITMENT", "APPLICATION_OPEN"):
        raise ApiError(ERR_WRONG_CYCLE_PHASE, "referrals are accepted only in RECRUITMENT or APPLICATION_OPEN")
    student = store.students.get(values["student_id"])
    if student is None:
        raise ApiError(ERR_NOT_FOUND, "student not found")
    # Polymorphic referrer identity from role + X-User-ID.
    referral = store.create(store.referrals, {
        "student_id": values["student_id"],
        "cycle_id": values["cycle_id"],
        "counselor_id": uid if role == "Counselor" else None,
        "partner_id": uid if role == "PartnerStaff" else None,
        "note": values["note"],
        "status": "NOMINATED",
    })
    return ok_object(serializers.referral(referral), 201)


@bp.post("/referrals/<referral_id>/revoke")
def revoke_referral(referral_id):
    role, uid = identity()
    require_roles(role, ("Counselor", "PartnerStaff", "ProgramAdmin"))
    referral = get_referral_or_404(referral_id)
    check_referral_ownership(role, uid, referral)
    if referral["status"] != "NOMINATED":
        raise ApiError(ERR_INVALID_STATE, "only a NOMINATED referral can be revoked")
    referral["status"] = "REVOKED"
    store.touch(referral)
    return ok_object(serializers.referral(referral))


@bp.get("/referrals")
def list_referrals():
    role, _ = identity()
    require_roles(role, LIST_ROLES)
    items = list(store.referrals.values())
    for field in ("student_id", "counselor_id", "partner_id", "cycle_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r[field] == value]
    items.sort(key=lambda r: r["created_at"])
    return paginated(items, serializers.referral)


@bp.get("/referrals/<referral_id>")
def get_referral(referral_id):
    role, uid = identity()
    require_roles(role, LIST_ROLES)
    referral = get_referral_or_404(referral_id)
    check_referral_ownership(role, uid, referral)
    return ok_object(serializers.referral(referral))
