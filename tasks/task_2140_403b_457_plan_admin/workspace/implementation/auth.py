"""Authentication, RBAC and ownership helpers (PRD 2.1, ladder rungs 1, 2, 6)."""
import functools

from flask import g, request

import store
from errors import ApiError

ROLES = {"SystemOperator", "PlanSponsorAdmin", "ComplianceOfficer",
         "VendorRepresentative", "Participant"}

ALL_ROLES = ["SystemOperator", "PlanSponsorAdmin", "ComplianceOfficer",
             "VendorRepresentative", "Participant"]


def endpoint(roles):
    """Rung 1 then rung 2, in that order, before anything else runs."""
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "X-User-ID and a recognised X-User-Role are required.")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED_ROLE",
                               "Role %s may not call this endpoint." % role)
            g.user_id = user_id
            g.role = role
            with store.LOCK:
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def deny_owner(msg="The acting principal does not own this resource."):
    raise ApiError("ERR_NOT_RESOURCE_OWNER", msg)


def require(cond, msg=None):
    if not cond:
        deny_owner(msg or "The acting principal does not own this resource.")


# ---------------------------------------------------------------------------
# Existence lookups -- each raises the collection's own not-found error.
# ---------------------------------------------------------------------------
def _get(coll, row_id, err):
    row = coll.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(err)
    return row


def employer(row_id):
    return _get(store.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")


def plan(row_id):
    return _get(store.plans, row_id, "ERR_PLAN_NOT_FOUND")


def vendor(row_id):
    return _get(store.vendors, row_id, "ERR_VENDOR_NOT_FOUND")


def participant(row_id):
    return _get(store.participants, row_id, "ERR_PARTICIPANT_NOT_FOUND")


def isa(row_id):
    return _get(store.isas, row_id, "ERR_ISA_NOT_FOUND")


def determination(row_id):
    return _get(store.eligibility_determinations, row_id, "ERR_ELIGIBILITY_NOT_FOUND")


def vendor_account(row_id):
    return _get(store.vendor_accounts, row_id, "ERR_VENDOR_ACCOUNT_NOT_FOUND")


def election(row_id):
    return _get(store.contribution_elections, row_id, "ERR_ELECTION_NOT_FOUND")


def batch(row_id):
    return _get(store.remittance_batches, row_id, "ERR_REMITTANCE_BATCH_NOT_FOUND")


def correction(row_id):
    return _get(store.remittance_corrections, row_id, "ERR_CORRECTION_NOT_FOUND")


def participant_request(row_id):
    return _get(store.participant_requests, row_id, "ERR_PARTICIPANT_REQUEST_NOT_FOUND")


def movement(row_id):
    return _get(store.transfer_exchange_requests, row_id, "ERR_TRANSFER_REQUEST_NOT_FOUND")


# ---------------------------------------------------------------------------
# Ownership predicates
# ---------------------------------------------------------------------------
def own_plan(plan_row):
    """PlanSponsorAdmin owns a plan whose employer_id is its X-User-ID."""
    if g.role == "PlanSponsorAdmin":
        require(plan_row["employer_id"] == g.user_id)


def own_participant(part_row):
    if g.role == "Participant":
        require(part_row["id"] == g.user_id)
    elif g.role == "PlanSponsorAdmin":
        require(part_row["employer_id"] == g.user_id)


def own_vendor_account(va_row):
    if g.role == "VendorRepresentative":
        require(va_row["vendor_id"] == g.user_id)
    elif g.role == "PlanSponsorAdmin":
        own_plan(store.plans[va_row["plan_id"]])
    elif g.role == "Participant":
        require(va_row["participant_id"] == g.user_id)


def own_isa(isa_row):
    if g.role == "VendorRepresentative":
        require(isa_row["vendor_id"] == g.user_id)
    elif g.role == "PlanSponsorAdmin":
        own_plan(store.plans[isa_row["plan_id"]])
