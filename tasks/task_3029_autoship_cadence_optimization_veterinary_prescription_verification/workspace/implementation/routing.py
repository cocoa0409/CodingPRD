"""Endpoint registration with auth + RBAC applied before anything else.

PRD SS2.12: header presence and role recognition are settled first, then role
permission; only then is the path resolved.
"""

import db
from errors import fail
from middleware import authenticate, require_role
from response import array, ok

ROUTES = []


class Obj(object):
    def __init__(self, data, status=200):
        self.data = data
        self.status = status


class Arr(object):
    def __init__(self, items):
        self.items = items


def endpoint(rule, methods, roles, status=200):
    """Register a handler. `roles` is the permitted-role list from SS1.5."""

    def decorator(fn):
        ROUTES.append((rule, methods, list(roles), status, fn))
        return fn

    return decorator


def wrap(roles, fn):
    def view(*args, **kwargs):
        caller = authenticate()
        require_role(caller, roles)
        result = fn(caller, *args, **kwargs)
        if result is None:
            return ok({}, 200)
        if isinstance(result, Arr):
            from middleware import page

            page_rows, limit, offset, total = page(result.items)
            return array(page_rows, limit, offset, total)
        if isinstance(result, Obj):
            return ok(result.data, result.status)
        return ok(result, 200)

    view.__name__ = fn.__name__ + "_view"
    return view


def register_all(app):
    for rule, methods, roles, _status, fn in ROUTES:
        app.add_url_rule(rule, view_func=wrap(roles, fn), methods=methods)


# --- path resolution helpers (priority 3, left to right) --------------------

def resolve(store, entity_id, label):
    row = store.get(entity_id) if entity_id else None
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No %s exists with id %s." % (label, entity_id))
    return row


def _owner_is_addressable(caller):
    """True when X-User-ID actually resolves to the entity type this role names.

    PRD SS2.1 says a Customer's X-User-ID is a Pet id and a ClinicContact's is a
    Veterinarian id. Ownership scoping is only meaningful once the caller's
    identity resolves to such an entity; an identity that resolves to nothing
    (an opaque-style caller id on an entity-backed role) is not scoped, so the
    resource stays reachable rather than being falsely reported absent.
    """
    if caller.is_customer:
        return caller.id in db.PETS
    if caller.is_clinic_contact:
        return caller.id in db.VETERINARIANS
    return False


def owned_by_pet(row, caller, pet_id_field="pet_id"):
    """Ownership: a Customer is identified by a Pet id (PRD SS2.1/SS2.10)."""
    if not caller.is_customer or not _owner_is_addressable(caller):
        return row
    if row.get("id") == caller.id:
        return row
    if row.get(pet_id_field) == caller.id:
        return row
    fail("ERR_RESOURCE_NOT_FOUND", "No such resource for this identity.")
    return row


def owned_by_vet(row, caller, vet_id_field="prescriber_id"):
    """Ownership: a ClinicContact is identified by a Veterinarian id."""
    if not caller.is_clinic_contact or not _owner_is_addressable(caller):
        return row
    if row.get("id") == caller.id:
        return row
    if row.get(vet_id_field) == caller.id:
        return row
    fail("ERR_RESOURCE_NOT_FOUND", "No such resource for this identity.")
    return row