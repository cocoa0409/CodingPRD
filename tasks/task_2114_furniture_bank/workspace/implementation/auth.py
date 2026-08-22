"""Authentication, role authorization and ownership scoping.

PRD 2.1 (headers and identity semantics), 2.9 rules 1, 2, 7, 8, 9.
"""

from flask import request

from core import ROLES
from db import db
from errors import ApiError


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Rule 1 then rule 2 of the rejection precedence."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(user_id, role)


# --------------------------------------------------------------------------
# Path / body resource resolution (rules 5 and 6)
# --------------------------------------------------------------------------
_COLLECTIONS = {
    "agency": ("agencies", "ERR_AGENCY_NOT_FOUND"),
    "client": ("clients", "ERR_CLIENT_NOT_FOUND"),
    "referral": ("referrals", "ERR_REFERRAL_NOT_FOUND"),
    "voucher": ("vouchers", "ERR_VOUCHER_NOT_FOUND"),
    "offer": ("donation_offers", "ERR_DONATION_OFFER_NOT_FOUND"),
    "inventory_item": ("inventory_items", "ERR_INVENTORY_ITEM_NOT_FOUND"),
    "truck": ("trucks", "ERR_TRUCK_NOT_FOUND"),
    "run": ("delivery_runs", "ERR_RUN_NOT_FOUND"),
    "stop": ("delivery_stops", "ERR_STOP_NOT_FOUND"),
    "volunteer": ("volunteers", "ERR_VOLUNTEER_NOT_FOUND"),
    "crew_assignment": ("crew_assignments", "ERR_CREW_ASSIGNMENT_NOT_FOUND"),
    "waitlist_entry": ("waitlist_entries", "ERR_WAITLIST_ENTRY_NOT_FOUND"),
}


def resolve(kind, identifier):
    collection_name, error_id = _COLLECTIONS[kind]
    collection = getattr(db, collection_name)
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, "No %s carries that id." % kind.replace("_", " "))
    return row


# --------------------------------------------------------------------------
# Scoping (rules 7 and 8)
# --------------------------------------------------------------------------
def require_agency_scope(actor, agency_id):
    """A CaseManager acts only inside the agency named by X-User-ID."""
    if actor.role != "CaseManager":
        return
    if agency_id != actor.user_id:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION",
                       "This resource belongs to another partner agency.")


def require_self_scope(actor, volunteer_id):
    """A Volunteer answers only their own invitation and reads only their own row."""
    if actor.role != "Volunteer":
        return
    if volunteer_id != actor.user_id:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION",
                       "A volunteer may only act on their own records.")
