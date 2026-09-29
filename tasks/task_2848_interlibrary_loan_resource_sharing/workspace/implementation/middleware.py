"""Authentication, RBAC, ownership and path resolution (PRD 2.1, 2.8, 2.9)."""
from flask import request

from db import db
from errors import ApiError

PATRON = "Patron"
ILL_STAFF = "IllBorrowingStaff"
PARTNER_AGENT = "PartnerAgent"
ACQUISITIONS = "AcquisitionsLibrarian"
ACCOUNTANT = "ConsortiumAccountant"
ADMIN = "LibraryAdmin"

ROLES = (PATRON, ILL_STAFF, PARTNER_AGENT, ACQUISITIONS, ACCOUNTANT, ADMIN)


def auth(*allowed):
    """Rung 10 then rung 20 of the rejection ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return str(user_id), role


# --- path resolution (rung 30) -------------------------------------------

def _get(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_patron(row_id):
    return _get(db.patrons, row_id, "ERR_PATRON_NOT_FOUND")


def get_partner(row_id):
    return _get(db.partners, row_id, "ERR_PARTNER_NOT_FOUND")


def get_agreement(row_id):
    return _get(db.agreements, row_id, "ERR_AGREEMENT_NOT_FOUND")


def get_rota(row_id):
    return _get(db.rotas, row_id, "ERR_ROTA_NOT_FOUND")


def get_rota_entry(row_id):
    return _get(db.rota_entries, row_id, "ERR_ROTA_ENTRY_NOT_FOUND")


def get_bib_item(row_id):
    return _get(db.bib_items, row_id, "ERR_BIB_ITEM_NOT_FOUND")


def get_request(row_id):
    return _get(db.requests, row_id, "ERR_REQUEST_NOT_FOUND")


def get_offer(row_id):
    return _get(db.offers, row_id, "ERR_OFFER_NOT_FOUND")


def get_shipment(row_id):
    return _get(db.shipments, row_id, "ERR_SHIPMENT_NOT_FOUND")


def get_loan(row_id):
    return _get(db.loans, row_id, "ERR_LOAN_NOT_FOUND")


def get_delivery(row_id):
    return _get(db.deliveries, row_id, "ERR_DELIVERY_NOT_FOUND")


def get_pod_order(row_id):
    return _get(db.pod_orders, row_id, "ERR_POD_ORDER_NOT_FOUND")


def get_invoice(row_id):
    return _get(db.invoices, row_id, "ERR_INVOICE_NOT_FOUND")


def get_lending_charge(row_id):
    return _get(db.lending_charges, row_id, "ERR_LENDING_CHARGE_NOT_FOUND")


# --- ownership (rung 25) -------------------------------------------------

def deny_owner():
    raise ApiError("ERR_NOT_RESOURCE_OWNER")


def own_patron_id(patron_id, user_id, role):
    """A Patron may only address their own account."""
    if role == PATRON and patron_id != user_id:
        deny_owner()


def own_partner_id(partner_id, user_id, role):
    """A PartnerAgent may only address its own partner record and children."""
    if role == PARTNER_AGENT and partner_id != user_id:
        deny_owner()


def own_request(req, user_id, role, partner_side=False):
    if role == PATRON and req.get("patron_id") != user_id:
        deny_owner()
    if partner_side and role == PARTNER_AGENT:
        if req.get("committed_partner_id") != user_id:
            deny_owner()


def own_loan(loan, user_id, role):
    req = db.requests.get(loan.get("request_id"))
    if req is None:
        return
    own_request(req, user_id, role, partner_side=True)


def own_delivery(delivery, user_id, role):
    req = db.requests.get(delivery.get("request_id"))
    if req is None:
        return
    own_request(req, user_id, role, partner_side=True)


def own_shipment(shipment, user_id, role):
    req = db.requests.get(shipment.get("request_id"))
    if req is None:
        return
    own_request(req, user_id, role, partner_side=True)


def own_offer(offer, user_id, role):
    own_partner_id(offer.get("partner_id"), user_id, role)


def own_invoice(invoice, user_id, role):
    own_partner_id(invoice.get("partner_id"), user_id, role)
