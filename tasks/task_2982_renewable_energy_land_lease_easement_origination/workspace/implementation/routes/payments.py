"""The option-payment ledger: reads only (PRD section 3.6, final paragraph).

Rows are minted by cascades and never posted directly, so this collection is
the only way to discover them. Ordering is created_at ascending then
sequence_no ascending.
"""

from flask import Blueprint

import access
import serializers as ser
import validation as v
from auth import LANDOWNER, PAYMENT_ADMINISTRATOR, PORTFOLIO_MANAGER, require
from envelope import ok, ok_list
from errors import ERR_OPTION_AGREEMENT_NOT_FOUND, fail
from store import db

bp = Blueprint("payments", __name__, url_prefix="/land-origination")

READERS = (PORTFOLIO_MANAGER, PAYMENT_ADMINISTRATOR, LANDOWNER)


def _owner_of(payment_row):
    agreement = db.options.get(payment_row["option_agreement_id"])
    return agreement["landowner_id"] if agreement is not None else None


@bp.get("/option-payments/<payment_id>")
@require(*READERS)
def get_payment(payment_id):
    # The catalogue carries no payment-specific 404, so an unknown ledger row
    # is reported against the agreement it would have belonged to.
    row = db.payments.get(payment_id) if isinstance(payment_id, str) else None
    if row is None:
        fail(ERR_OPTION_AGREEMENT_NOT_FOUND)
    access.own_payment(row)
    return ok(ser.option_payment(row))


@bp.get("/option-payments")
@require(*READERS)
def list_payments():
    limit, offset = v.pagination()
    rows = sorted(db.payments.values(),
                  key=lambda r: (r["created_at"], int(r["sequence_no"])))
    rows = access.scope_rows(rows, _owner_of)
    rows = v.apply_filters(rows, [
        ("option_agreement_id", v.query_str("option_agreement_id")),
        ("payment_kind", v.query_str("payment_kind")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.option_payment, page), limit, offset, total)
