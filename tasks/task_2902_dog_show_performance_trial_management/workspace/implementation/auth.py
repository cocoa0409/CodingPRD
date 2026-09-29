"""Authentication, RBAC and entity lookup helpers."""
from flask import request

from common import ROLES
from errors import fail
import store

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Bands 1 and 2 of the rejection ladder."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        fail("ERR_ROLE_NOT_PERMITTED", "Unrecognised role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED",
             "Role '%s' may not call this endpoint." % role)
    return user_id, role


def owner_check(user_id, owner_id):
    if user_id != owner_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "The caller does not own the target resource.")


# ------------------------------------------------------------------- lookups
_NOT_FOUND = {
    "clubs": "ERR_CLUB_NOT_FOUND",
    "shows": "ERR_SHOW_NOT_FOUND",
    "judges": "ERR_JUDGE_NOT_FOUND",
    "slots": "ERR_SLOT_NOT_FOUND",
    "classes": "ERR_CLASS_NOT_FOUND",
    "handlers": "ERR_HANDLER_NOT_FOUND",
    "dogs": "ERR_DOG_NOT_FOUND",
    "entries": "ERR_ENTRY_NOT_FOUND",
    "blocks": "ERR_RING_BLOCK_NOT_FOUND",
    "protests": "ERR_PROTEST_NOT_FOUND",
    "filings": "ERR_FILING_NOT_FOUND",
}


def must_get(collection, ident):
    rec = store.get(collection, ident)
    if rec is None:
        fail(_NOT_FOUND[collection], "%s does not name an existing row." % ident)
    return rec
