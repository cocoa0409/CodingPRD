"""Headers, roles and ownership (PRD 2.1 / 2.9 checks 1-3 and 7)."""

from flask import request

from errors import ApiError
from store import db

PLATFORM_ADMIN = "PlatformAdmin"
BROKER = "Broker"
BUYER = "Buyer"
SELLER = "Seller"
REGULATOR = "RegulatorAnalyst"
ESCROW_OFFICER = "EscrowOfficer"

ALL_ROLES = (PLATFORM_ADMIN, BROKER, BUYER, SELLER, REGULATOR, ESCROW_OFFICER)


def authenticate(allowed_roles):
    """Checks 1-3: headers present, role recognised, role permitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-Role header is required.")
    role = role.strip()
    user_id = str(user_id).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-Role header carries an unrecognised role.")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role %s may not call this endpoint." % role)
    return user_id, role


def not_owner():
    raise ApiError("ERR_NOT_RESOURCE_OWNER", "The caller does not own this resource.")


def require_brokerage(user_id, role, brokerage_id):
    if role == BROKER and user_id != brokerage_id:
        not_owner()


def require_buyer(user_id, role, buyer_id):
    if role == BUYER and user_id != buyer_id:
        not_owner()


def require_seller(user_id, role, seller_id):
    if role == SELLER and user_id != seller_id:
        not_owner()


def fetch(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    rec = collection.get(key)
    if rec is None:
        raise ApiError(error_id)
    return rec


def county_or_404(county_id):
    return fetch(db.counties, county_id, "ERR_COUNTY_NOT_FOUND")


def seller_or_404(seller_id):
    return fetch(db.sellers, seller_id, "ERR_SELLER_NOT_FOUND")


def buyer_or_404(buyer_id):
    return fetch(db.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")


def brokerage_or_404(brokerage_id):
    return fetch(db.brokerages, brokerage_id, "ERR_BROKERAGE_NOT_FOUND")


def license_or_404(license_id):
    return fetch(db.licenses, license_id, "ERR_LICENSE_NOT_FOUND")


def premises_or_404(premises_id):
    return fetch(db.premises, premises_id, "ERR_PREMISES_NOT_FOUND")


def listing_or_404(listing_id):
    return fetch(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")


def agreement_or_404(agreement_id):
    return fetch(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def disclosure_or_404(disclosure_id):
    return fetch(db.disclosures, disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")


def application_or_404(application_id):
    return fetch(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")


def protest_or_404(protest_id):
    return fetch(db.protests, protest_id, "ERR_PROTEST_NOT_FOUND")


def filing_or_404(filing_id):
    return fetch(db.filings, filing_id, "ERR_FILING_NOT_FOUND")


def entry_or_404(entry_id):
    return fetch(db.ledger, entry_id, "ERR_ENTRY_NOT_FOUND")
