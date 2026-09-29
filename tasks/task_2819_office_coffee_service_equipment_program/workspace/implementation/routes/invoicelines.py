"""Invoice line discovery (PRD 3.8).

Every line below CREDIT is synthesized by draft assembly rather than posted by a
client, so this listing is the only channel through which they can be observed.
"""
from flask import Blueprint

import lookup
import serializers
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_CUSTOMER_CONTACT,
                   authenticate)
from envelope import ok
from store import db

bp = Blueprint("invoicelines", __name__)

READ_ROLES = (ROLE_BILLING_SPECIALIST, ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT)


@bp.get("/ocs/invoice-lines")
def list_invoice_lines():
    authenticate(READ_ROLES)
    rows = lookup.eq_filter(list(db.invoice_lines.values()), "invoice_id")
    rows = lookup.eq_filter(rows, "site_id")
    rows = lookup.eq_filter(rows, "target_line_id")
    rows = lookup.eq_filter(rows, "line_type")
    rows = lookup.eq_filter(rows, "product_id")
    return lookup.listing(rows, serializers.invoice_line)


@bp.get("/ocs/invoice-lines/<line_id>")
def read_invoice_line(line_id):
    authenticate(READ_ROLES)
    return ok(serializers.invoice_line(lookup.invoice_line(line_id)))
