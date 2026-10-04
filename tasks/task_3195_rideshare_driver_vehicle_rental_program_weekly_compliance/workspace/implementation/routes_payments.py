"""Recorded rental payment reads."""

from flask import Blueprint, request

import db
import services as svc
from response import ok, ok_list
from services import by_created, get_week, paginate


bp = Blueprint("payments", __name__)

PAYMENT_OUTCOMES = ("SUCCEEDED", "FAILED")


def _get_payment(payment_id):
    from errors import E_NOT_FOUND
    row = db.PAYMENTS.get(payment_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No rental payment exists with id %s." % payment_id)
    return row


@bp.get("/program/payments")
def list_payments():
    rows = by_created(db.PAYMENTS.values())
    for key in ("agreement_id", "week_id", "payment_outcome"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.payment_out(r) for r in page], limit, offset, total)


@bp.get("/program/payments/<payment_id>")
def get_one_payment(payment_id):
    return ok(svc.payment_out(_get_payment(payment_id)))