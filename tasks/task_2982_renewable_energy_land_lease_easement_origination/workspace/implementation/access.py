"""Reference resolution (ladder rungs 3-13) and Landowner read scoping.

Path identifiers resolve strictly left to right; body foreign keys resolve
after every path identifier, in the order the endpoint declares them.
"""

from auth import acting_user_id, is_landowner_actor
from errors import (
    ERR_CORRIDOR_NOT_FOUND,
    ERR_CROSSING_AGREEMENT_NOT_FOUND,
    ERR_LANDOWNER_NOT_FOUND,
    ERR_LEASE_AGREEMENT_NOT_FOUND,
    ERR_NEIGHBOR_CONSENT_NOT_FOUND,
    ERR_OPTION_AGREEMENT_NOT_FOUND,
    ERR_PARCEL_NOT_FOUND,
    ERR_RENT_INVOICE_NOT_FOUND,
    ERR_SETBACK_RULE_NOT_FOUND,
    ERR_SITE_ACCESS_BOOKING_NOT_FOUND,
    ERR_TITLE_CURATIVE_ITEM_NOT_FOUND,
    ERR_UNAUTHORIZED,
    fail,
)
from store import db


def _need(collection, key, error_id):
    row = getattr(db, collection).get(key) if isinstance(key, str) else None
    if row is None:
        fail(error_id)
    return row


def landowner(key):
    return _need("landowners", key, ERR_LANDOWNER_NOT_FOUND)


def parcel(key):
    return _need("parcels", key, ERR_PARCEL_NOT_FOUND)


def setback_rule(key):
    return _need("setback_rules", key, ERR_SETBACK_RULE_NOT_FOUND)


def consent(key):
    return _need("consents", key, ERR_NEIGHBOR_CONSENT_NOT_FOUND)


def curative_item(key):
    return _need("curative_items", key, ERR_TITLE_CURATIVE_ITEM_NOT_FOUND)


def option(key):
    return _need("options", key, ERR_OPTION_AGREEMENT_NOT_FOUND)


def corridor(key):
    return _need("corridors", key, ERR_CORRIDOR_NOT_FOUND)


def crossing(key):
    return _need("crossings", key, ERR_CROSSING_AGREEMENT_NOT_FOUND)


def booking(key):
    return _need("bookings", key, ERR_SITE_ACCESS_BOOKING_NOT_FOUND)


def lease(key):
    return _need("leases", key, ERR_LEASE_AGREEMENT_NOT_FOUND)


def invoice(key):
    return _need("invoices", key, ERR_RENT_INVOICE_NOT_FOUND)


# ------------------------------------------------------ Landowner scoping
def own(landowner_id):
    """A Landowner principal may only reach rows referencing their own id."""
    if is_landowner_actor() and landowner_id != acting_user_id():
        fail(ERR_UNAUTHORIZED)


def own_payment(payment_row):
    if not is_landowner_actor():
        return
    agreement = db.options.get(payment_row["option_agreement_id"])
    owner = agreement["landowner_id"] if agreement else None
    own(owner)


def own_invoice(invoice_row):
    if not is_landowner_actor():
        return
    lease_row = db.leases.get(invoice_row["lease_agreement_id"])
    owner = lease_row["landowner_id"] if lease_row else None
    own(owner)


def scope_rows(rows, owner_of):
    """Filter a list read down to the acting Landowner's own rows."""
    if not is_landowner_actor():
        return rows
    me = acting_user_id()
    return [r for r in rows if owner_of(r) == me]
