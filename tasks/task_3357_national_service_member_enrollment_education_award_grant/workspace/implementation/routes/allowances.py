from flask import Blueprint

import auth
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("allowances", __name__)


@bp.route("/enrollments/<enrollmentId>/allowance-payments", methods=["POST"])
def create_allowance_payment(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        award = db.store.awards.get(enrollment["award_id"])
        if award is not None:
            auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    body = util.body_json()
    amount = body.get("amount_cents")
    note = body.get("note")
    if not util.is_int(amount) or amount < 1:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "amount_cents must be a positive integer"
        )
    if note is not None and not util.is_str(note):
        raise ApiError("ERR_INVALID_REQUEST", 400, "note must be a string")
    # The state check precedes every fiscal check (PRD 3.6).
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE")
    total = C.ALLOWANCE_TOTAL_CENTS[enrollment["term_category"]]
    paid = enrollment["allowance_paid_cents"]
    earned_cap = (total * enrollment["certified_minutes"]) // enrollment["term_minutes"]
    # Pinned fiscal gate order: period cap, term total, earned cap.
    if amount > C.ALLOWANCE_PERIOD_MAX_CENTS:
        raise ApiError(
            "ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED",
            422,
            "A single payment may not exceed 100000 cents",
        )
    if paid + amount > total:
        raise ApiError(
            "ERR_ALLOWANCE_EXHAUSTED",
            422,
            "Payment would exceed the term allowance total",
        )
    if paid + amount > earned_cap:
        raise ApiError(
            "ERR_ALLOWANCE_EARNED_CAP_EXCEEDED",
            422,
            "Payment would exceed the hours-earned allowance cap",
        )
    payment = db.new_entity(
        {
            "id": util.new_id(),
            "enrollment_id": enrollmentId,
            "amount_cents": amount,
            "note": note,
        },
        common=False,  # LivingAllowancePayment carries id + created_at only (PRD 2.5)
    )
    db.store.payments[payment["id"]] = payment
    enrollment["allowance_paid_cents"] += amount
    domain.touch(enrollment)
    return util.ok(serialize(payment), 201)
