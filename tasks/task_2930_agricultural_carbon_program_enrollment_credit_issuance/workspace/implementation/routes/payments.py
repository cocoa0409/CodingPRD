"""Grower payment discovery and settlement (section 3.9)."""

from flask import Blueprint

import db
import middleware as mw
import response as resp
from services import common, serialize

bp = Blueprint("payments", __name__)

FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "credit_batch_id": ("credit_batch_id", "str"),
    "crop_year": ("crop_year", "int"),
    "status": ("status", "str"),
    "payment_model": ("payment_model", "str"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)


@bp.route("/grower-payments", methods=["GET"])
def list_payments():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.grower_payments.values(), FILTERS)
    return resp.paginate(rows, serialize.grower_payment)


@bp.route("/grower-payments/<grower_payment_id>", methods=["GET"])
def read_payment(grower_payment_id):
    mw.authorize(*READ_ROLES)
    row = common.get_grower_payment(grower_payment_id)
    enrollment = db.enrollments.get(row["enrollment_id"])
    if enrollment is not None:
        mw.require_grower_owner(enrollment["grower_id"])
    return resp.object_response(serialize.grower_payment(row))


@bp.route("/grower-payments/<grower_payment_id>/pay", methods=["POST"])
def pay_payment(grower_payment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    payment = common.get_grower_payment(grower_payment_id)
    enrollment = db.enrollments[payment["enrollment_id"]]
    grower = db.growers[enrollment["grower_id"]]

    if payment["status"] != "ACCRUED":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only an ACCRUED payment may be settled.")
    if enrollment["permanence_status"] == "BREACHED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A payment on an enrollment whose permanence is BREACHED may not be settled.",
        )
    if grower["status"] != "ACTIVE":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Settlement requires an ACTIVE grower."
        )
    if grower["outstanding_clawback_cents"] > 0:
        common.fail("ERR_CLAWBACK_OUTSTANDING")

    payment["status"] = "PAID"
    payment["paid_at"] = db.now_raw()
    db.touch(payment)
    grower["net_paid_cents"] = grower["net_paid_cents"] + payment["net_amount_cents"]
    db.touch(grower)
    return resp.object_response(serialize.grower_payment(payment))
