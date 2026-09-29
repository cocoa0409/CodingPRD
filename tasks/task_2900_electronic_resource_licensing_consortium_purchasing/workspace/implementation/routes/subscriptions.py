"""Section 3.5 and 3.7 - subscription reads, cost-per-use and the invoice split."""

from flask import Blueprint, request

import auth
import calc
import envelope
import shape
import store

bp = Blueprint("subscriptions", __name__)


@bp.get("/erm/subscriptions/<subscription_id>")
def read_subscription(subscription_id):
    auth.require_roles(*auth.ALL_ROLES)
    row = auth.get_subscription(subscription_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/subscriptions")
def list_subscriptions():
    auth.require_roles(*auth.ALL_ROLES)
    rows = list(store.subscriptions.values())
    for field in ("product_id", "negotiation_id", "contract_status", "access_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)


@bp.get("/erm/subscriptions/<subscription_id>/cost-per-use")
def subscription_cost_per_use(subscription_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN)
    subscription = auth.get_subscription(subscription_id)
    as_of_month = request.args.get("as_of_month")
    if as_of_month is not None:
        if not shape.MONTH_RE.match(as_of_month):
            shape.bad("as_of_month must be a calendar month in YYYY-MM form.")
    result = calc.cost_per_use(subscription, as_of_month=as_of_month)
    return envelope.object_response(result)


@bp.get("/erm/subscriptions/<subscription_id>/invoice-allocation")
def subscription_invoice_allocation(subscription_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN)
    subscription = auth.get_subscription(subscription_id)
    return envelope.object_response(calc.consortium_invoice_allocation(subscription))
