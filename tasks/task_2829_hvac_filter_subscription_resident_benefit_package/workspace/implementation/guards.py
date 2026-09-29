"""Ladder rungs 1-4 and 6: identity, role authorization, existence lookups,
ownership narrowing and list query-parameter validation (PRD 2.1, 2.3, 2.5, 2.10)."""
from flask import request

import envelope
from errors import fail
from store import db

ROLES = ("ProgramOperator", "PropertyManager", "Resident", "ClaimsAdjuster")


def identity():
    """Rung 1: both identity headers present and the role recognised."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return uid, role


def auth(allowed):
    """Rung 1 then rung 2."""
    uid, role = identity()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
    return uid, role


# --------------------------------------------------------------------------
# Rung 3: existence. Each missing referent has its own 404 (PRD 2.5).
# --------------------------------------------------------------------------
def get_property(pid):
    rec = db.properties.get(pid) if isinstance(pid, str) else None
    if rec is None:
        fail("ERR_PROPERTY_NOT_FOUND")
    return rec


def get_unit(uid):
    rec = db.units.get(uid) if isinstance(uid, str) else None
    if rec is None:
        fail("ERR_UNIT_NOT_FOUND")
    return rec


def get_sku(sid):
    rec = db.skus.get(sid) if isinstance(sid, str) else None
    if rec is None:
        fail("ERR_SKU_NOT_FOUND")
    return rec


def get_resident(rid):
    rec = db.residents.get(rid) if isinstance(rid, str) else None
    if rec is None:
        fail("ERR_RESIDENT_NOT_FOUND")
    return rec


def get_subscription(sid):
    rec = db.subscriptions.get(sid) if isinstance(sid, str) else None
    if rec is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND")
    return rec


def get_shipment(sid):
    rec = db.shipments.get(sid) if isinstance(sid, str) else None
    if rec is None:
        fail("ERR_SHIPMENT_NOT_FOUND")
    return rec


def get_case(cid):
    rec = db.cases.get(cid) if isinstance(cid, str) else None
    if rec is None:
        fail("ERR_CASE_NOT_FOUND")
    return rec


def get_claim(cid):
    rec = db.claims.get(cid) if isinstance(cid, str) else None
    if rec is None:
        fail("ERR_CLAIM_NOT_FOUND")
    return rec


def get_transfer(tid):
    rec = db.transfers.get(tid) if isinstance(tid, str) else None
    if rec is None:
        fail("ERR_TRANSFER_NOT_FOUND")
    return rec


def get_entitlement(eid):
    rec = db.entitlements.get(eid) if isinstance(eid, str) else None
    if rec is None:
        fail("ERR_ENTITLEMENT_NOT_FOUND")
    return rec


# --------------------------------------------------------------------------
# Rung 4: ownership scope for the two entity-backed roles (PRD 2.1).
# --------------------------------------------------------------------------
def own_property(uid, role, property_id):
    if role == "PropertyManager" and uid != property_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def own_unit(uid, role, unit):
    own_property(uid, role, unit["property_id"])


def own_subscription(uid, role, sub):
    if role == "PropertyManager" and uid != sub["property_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if role == "Resident" and uid != sub["resident_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


def own_resident(uid, role, resident):
    if role == "Resident" and uid != resident["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------
# Rung 6: pagination and filter query parameters (PRD 2.3).
# --------------------------------------------------------------------------
def _int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        fail("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_PAGINATION")
    value = int(text)
    return value


def pagination(enum_filters=None, plain_filters=()):
    """Returns (limit, offset, filters). Rejects out-of-range pagination and any
    filter value that is not a member of the enumeration it filters on."""
    args = request.args
    limit = _int_param(args.get("limit"))
    offset = _int_param(args.get("offset"))
    if limit is None:
        limit = envelope.PAGINATION_DEFAULT_LIMIT
    elif limit < envelope.PAGINATION_MIN_LIMIT or limit > envelope.PAGINATION_MAX_LIMIT:
        fail("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = envelope.PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        fail("ERR_INVALID_PAGINATION")

    filters = {}
    for name, members in (enum_filters or {}).items():
        raw = args.get(name)
        if raw is None:
            continue
        if raw not in members:
            fail("ERR_INVALID_PAGINATION")
        filters[name] = raw
    for name in plain_filters:
        raw = args.get(name)
        if raw is None:
            continue
        filters[name] = raw
    return limit, offset, filters


def page(rows, limit, offset):
    return rows[offset:offset + limit]
