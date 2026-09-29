"""Shared helpers for the route modules: path resolution, list plumbing and
the vendor-scope check of PRD 2.1.
"""
import calc
import db
from db import store
from envelope import paginate, respond_list, respond_object
from errors import ApiError
from reqval import pagination_params

ALL_ROLES = db.ALL_ROLES


# --------------------------------------------------------------- rung 5 & 6
def resolve(collection, row_id, error_id):
    """Path or body identifier resolution; a miss is the matching 404."""
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def facility(row_id):
    return resolve(store.facilities, row_id, "ERR_FACILITY_NOT_FOUND")


def vendor(row_id):
    return resolve(store.vendors, row_id, "ERR_VENDOR_NOT_FOUND")


def vendor_rep(row_id):
    return resolve(store.vendor_reps, row_id, "ERR_VENDOR_REP_NOT_FOUND")


def credential(row_id):
    return resolve(store.credentials, row_id, "ERR_CREDENTIAL_NOT_FOUND")


def surgical_case(row_id):
    return resolve(store.surgical_cases, row_id, "ERR_SURGICAL_CASE_NOT_FOUND")


def authorization(row_id):
    return resolve(store.authorizations, row_id, "ERR_AUTHORIZATION_NOT_FOUND")


def pir(row_id):
    return resolve(store.pirs, row_id, "ERR_PIR_NOT_FOUND")


def approved_product(row_id):
    return resolve(store.approved_products, row_id, "ERR_APPROVED_PRODUCT_NOT_FOUND")


def loaner_set(row_id):
    return resolve(store.loaner_sets, row_id, "ERR_LOANER_SET_NOT_FOUND")


def check_in(row_id):
    return resolve(store.check_ins, row_id, "ERR_CHECK_IN_NOT_FOUND")


def incident(row_id):
    return resolve(store.incidents, row_id, "ERR_INCIDENT_NOT_FOUND")


def appeal(row_id):
    return resolve(store.appeals, row_id, "ERR_APPEAL_NOT_FOUND")


# ------------------------------------------------------------------- rung 7
def require_vendor_scope(role, user_id, vendor_id):
    """A VendorAdmin may act only on rows belonging to its own vendor."""
    if role == "VendorAdmin" and user_id != vendor_id:
        raise ApiError("ERR_VENDOR_SCOPE_VIOLATION")


def require_rep_scope(role, user_id, rep_id):
    """A VendorRepUser may act only on its own representative rows."""
    if role == "VendorRepUser" and user_id != rep_id:
        raise ApiError("ERR_VENDOR_SCOPE_VIOLATION")


def require_rep_or_vendor_scope(role, user_id, rep):
    require_rep_scope(role, user_id, rep["id"])
    require_vendor_scope(role, user_id, rep["vendor_id"])


# ------------------------------------------------------------------- lists
def listing(rows, limit, offset):
    """Order by creation timestamp ascending, then paginate (PRD 2.3)."""
    ordered = db.in_creation_order(rows)
    page, total = paginate(ordered, limit, offset)
    return respond_list([db.public(row) for row in page], limit, offset, total)


def ok(row, http_status=200):
    return respond_object(db.public(row), http_status)


def created(row):
    return respond_object(db.public(row), 201)


def matches(row, field, value):
    return value is None or row.get(field) == value
