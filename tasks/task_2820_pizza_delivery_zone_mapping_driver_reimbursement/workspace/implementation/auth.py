"""Identity, role gate, ownership scope and left-to-right path resolution.

Implements priorities 1-6 of the order of refusal (PRD 2.8) in that exact order:
missing identity, invalid role, unauthorized role, store scope, driver scope,
then the not-found errors of the path parameters.
"""
from flask import request

import db
from errors import ApiError, fail

ROLES = ("StoreManager", "Dispatcher", "Driver", "ComplianceOfficer", "CustomerCareAgent")
ALL_ROLES = ROLES

# The only nested path whose child must belong to the parent named before it.
PARENT_FIELD = {("dispatch", "dispatch_stop"): "dispatch_id"}


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_manager(self):
        return self.role == "StoreManager"

    @property
    def is_driver(self):
        return self.role == "Driver"


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_MISSING_USER_ID", "Header X-User-ID is required.")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ROLES:
        fail("ERR_INVALID_ROLE", "Header X-User-Role must name one of the five roles.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return Actor(user_id, role)


def peek_body():
    """The request body without any schema enforcement, for the scope checks."""
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def owning_store_id(kind, record):
    if record is None:
        return None
    if kind == "store":
        return record["id"]
    if kind in ("zone_version", "service_address", "driver", "vehicle_cost_model", "order"):
        return record["store_id"]
    if kind == "address_dispute":
        return owning_store_id("service_address", db.service_addresses.get(record["service_address_id"]))
    if kind == "dispatch":
        return owning_store_id("driver", db.drivers.get(record["driver_id"]))
    if kind == "dispatch_stop":
        return owning_store_id("dispatch", db.dispatches.get(record["dispatch_id"]))
    if kind == "safe_drop":
        return owning_store_id("driver", db.drivers.get(record["driver_id"]))
    if kind == "complaint":
        return owning_store_id("order", db.orders.get(record["order_id"]))
    if kind == "reimbursement_line":
        return owning_store_id("driver", db.drivers.get(record["driver_id"]))
    # MvrCheck and InsuranceVerification carry no store reference of their own.
    return None


def owning_driver_id(kind, record):
    if record is None:
        return None
    if kind == "driver":
        return record["id"]
    if kind in ("dispatch", "safe_drop", "reimbursement_line"):
        return record["driver_id"]
    if kind == "dispatch_stop":
        dispatch = db.dispatches.get(record["dispatch_id"])
        return dispatch["driver_id"] if dispatch else None
    return None


def _resolve_chain(chain):
    resolved = []
    broken = False
    previous = None
    for kind, ident in chain:
        record = None if broken else db.lookup(kind, ident)
        if record is not None and previous is not None:
            field = PARENT_FIELD.get((previous[0], kind))
            if field is not None and record.get(field) != previous[1]["id"]:
                record = None
        if record is None:
            broken = True
        resolved.append((kind, ident, record))
        previous = (kind, record) if record is not None else previous
    return resolved


def _scope(actor, targets):
    if actor.is_manager:
        for kind, record in targets:
            store_id = owning_store_id(kind, record)
            if store_id is not None and store_id != actor.user_id:
                fail("ERR_FORBIDDEN_STORE_SCOPE", "This resource belongs to another store.")
    elif actor.is_driver:
        for kind, record in targets:
            driver_id = owning_driver_id(kind, record)
            if driver_id is not None and driver_id != actor.user_id:
                fail("ERR_FORBIDDEN_DRIVER_SCOPE", "This resource belongs to another driver.")


def guard(actor, chain=(), body_scope=()):
    """Resolve the path, apply the scope rules, then report the first 404."""
    resolved = _resolve_chain(chain)
    targets = [(kind, record) for kind, _ident, record in resolved if record is not None]
    for field, kind in body_scope:
        ident = peek_body().get(field)
        record = db.lookup(kind, ident)
        if record is not None:
            targets.append((kind, record))
    _scope(actor, targets)
    for kind, _ident, record in resolved:
        if record is None:
            fail(db.NOT_FOUND[kind])
    return [record for _kind, _ident, record in resolved]


def body_fk(kind, ident):
    """Priority 7: a foreign key supplied in the body must resolve."""
    record = db.lookup(kind, ident)
    if record is None:
        raise ApiError(db.NOT_FOUND[kind])
    return record
