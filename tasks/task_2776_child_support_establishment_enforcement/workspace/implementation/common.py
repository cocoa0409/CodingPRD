"""Path resolution, list filtering and the shared closed-case guard."""
from flask import request

import db
import middleware
from errors import ApiError

PREFIX = "/child-support"


# ---------------------------------------------------------- path resolution
def participant(pid):
    return db.get_or_404(db.participants, pid, "ERR_PARTICIPANT_NOT_FOUND")


def case(cid):
    return db.get_or_404(db.cases, cid, "ERR_CASE_NOT_FOUND")


def paternity_action(aid):
    return db.get_or_404(db.paternity_actions, aid, "ERR_PATERNITY_ACTION_NOT_FOUND")


def order(oid):
    return db.get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")


def employer(eid):
    return db.get_or_404(db.employers, eid, "ERR_EMPLOYER_NOT_FOUND")


def iwo(iid):
    return db.get_or_404(db.withholding_orders, iid, "ERR_IWO_NOT_FOUND")


def charge(cid):
    return db.get_or_404(db.charges, cid, "ERR_CHARGE_NOT_FOUND")


def payment(pid):
    return db.get_or_404(db.payments, pid, "ERR_PAYMENT_NOT_FOUND")


def review(rid):
    return db.get_or_404(db.modification_reviews, rid, "ERR_REVIEW_NOT_FOUND")


def enforcement_action(aid):
    return db.get_or_404(db.enforcement_actions, aid, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")


def referral(rid):
    return db.get_or_404(db.interstate_referrals, rid, "ERR_REFERRAL_NOT_FOUND")


def offer(oid):
    return db.get_or_404(db.compromise_offers, oid, "ERR_OFFER_NOT_FOUND")


# ------------------------------------------------------------- body FK refs
def ref_participant(pid):
    row = db.participants.get(pid) if isinstance(pid, str) else None
    if row is None:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


def ref_employer(eid):
    row = db.employers.get(eid) if isinstance(eid, str) else None
    if row is None:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


def ref_offer(oid):
    row = db.compromise_offers.get(oid) if isinstance(oid, str) else None
    if row is None:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


def ref_iwo(iid):
    row = db.withholding_orders.get(iid) if isinstance(iid, str) else None
    if row is None:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


# ------------------------------------------------------------------- guards
def case_writable(case_row):
    """A CLOSED case rejects every write, against itself or any child (PRD 2.9)."""
    if case_row["case_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_CASE_STATUS")


def case_of_order(order_row):
    return db.cases.get(order_row["case_id"])


def case_of_iwo(iwo_row):
    order_row = db.orders.get(iwo_row["order_id"])
    return db.cases.get(order_row["case_id"]) if order_row else None


def party_guard(case_row):
    if case_row is not None:
        middleware.require_case_party(case_row)


# ------------------------------------------------------------------ filters
def qp(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def qp_bool(name):
    raw = qp(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    raise ApiError("ERR_VALIDATION", "%s must be a boolean." % name)


def apply_filters(rows, specs):
    """specs: list of (query-param name, row field, coercion) triples."""
    out = rows
    for name, field, kind in specs:
        wanted = qp_bool(name) if kind == "bool" else qp(name)
        if wanted is None:
            continue
        out = [r for r in out if r.get(field) == wanted]
    return out
