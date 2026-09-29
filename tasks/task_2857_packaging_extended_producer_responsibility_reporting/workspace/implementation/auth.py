"""Authentication, role authorisation, ownership and per-row version bookkeeping.

PRD 2.1 pins the header names (`X-User-ID`, `X-User-Role`) and the four role
spellings; PRD 2.5 pins the admission order that this module's decorator drives.
"""
import functools

from flask import g, request

import store
from errors import fail

REGULATOR = "ProgramRegulator"
OFFICER = "ProducerComplianceOfficer"
PRO_ADMIN = "ProAdministrator"
VERIFIER = "IndependentVerifier"

ALL_ROLES = (REGULATOR, OFFICER, PRO_ADMIN, VERIFIER)

# 12 type-specific 404 codes, keyed by store collection (PRD 2.5 steps 4 and 5).
NOT_FOUND = {
    "producers": "ERR_PRODUCER_NOT_FOUND",
    "skus": "ERR_SKU_NOT_FOUND",
    "state_programs": "ERR_STATE_PROGRAM_NOT_FOUND",
    "reporting_periods": "ERR_REPORTING_PERIOD_NOT_FOUND",
    "pros": "ERR_PRO_NOT_FOUND",
    "fee_schedules": "ERR_FEE_SCHEDULE_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
    "memberships": "ERR_MEMBERSHIP_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "report_lines": "ERR_REPORT_LINE_NOT_FOUND",
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


def endpoint(roles):
    """Decorator running admission steps 1 and 2 of PRD 2.5 before the handler."""

    def decorate(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED")
            if role not in roles:
                fail("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.user_role = role
            g.touched = set()
            g.fresh = set()
            return view(*args, **kwargs)

        return wrapper

    return decorate


def user_id():
    return g.user_id


def role():
    return g.user_role


# --- version / updated_at bookkeeping -------------------------------------
#
# PRD 2.4: `version` increases by exactly 1 on every mutation of a row, and a
# cascade that touches five rows increments all five.  A single request must
# never advance one row twice, so the touched set is per-request.


def created(row):
    """Mark a row minted by this request so later cascades don't bump it to 2."""
    g.fresh.add(id(row))
    return row


def touch(row):
    if row is None:
        return None
    key = id(row)
    if key in g.fresh or key in g.touched:
        return row
    g.touched.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = store.now_stamp()
    return row


# --- ownership (PRD 2.1 / 2.5 step 6) -------------------------------------


def require_producer_owner(producer_id):
    if g.user_role == OFFICER and g.user_id != producer_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def require_pro_owner(pro_id):
    if g.user_role == PRO_ADMIN and g.user_id != pro_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def require_assigned_verifier(engagement):
    if g.user_id != engagement["verifier_user_id"]:
        fail("ERR_NOT_ASSIGNED_VERIFIER")


# --- resolution helpers ---------------------------------------------------


def must(kind, rid):
    row = store.get(kind, rid)
    if row is None:
        fail(NOT_FOUND[kind])
    return row


def new_row(kind, fields):
    stamp = store.now_stamp()
    row = {"id": store.new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    store.insert(kind, row)
    return created(row)
