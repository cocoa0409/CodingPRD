"""Authentication, role authorization, ownership (PRD 2.1) and reference resolution."""

from functools import wraps

from flask import request

import store
from common import ROLES
from errors import NOT_FOUND_FOR_KIND, ApiError

ROLE_SET = set(ROLES)

TABLE_OF = {
    "installer": "installers",
    "site": "sites",
    "load_calculation": "load_calculations",
    "battery_system": "battery_systems",
    "permit": "permits",
    "application": "applications",
    "program": "programs",
    "claim": "claims",
    "test": "tests",
    "alert": "alerts",
    "enrollment": "enrollments",
    "event": "events",
    "performance": "performances",
}

# Kinds whose ownership resolves through BatterySystem.battery_system_id.
_VIA_SYSTEM = ("permit", "application", "claim", "test", "alert", "enrollment")


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def current_actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and a recognised X-User-Role header are required.",
        )
    return Actor(user_id, role)


def guard(*roles):
    """Precedence steps 1 and 2: authentication then role authorization."""

    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            actor = current_actor()
            if actor.role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not call this endpoint." % actor.role,
                )
            return view(actor, *args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #

def _system_for(kind, record):
    if kind == "battery_system":
        return record
    if kind in _VIA_SYSTEM:
        return store.get("battery_systems", record.get("battery_system_id"))
    return None


def _installer_owners(kind, record):
    """The installer ids allowed to act, or None when the check does not apply."""
    if kind == "load_calculation":
        owners = set(
            system["installer_id"]
            for system in store.rows("battery_systems")
            if system.get("load_calculation_id") == record["id"]
        )
        return owners or None
    system = _system_for(kind, record)
    if system is None:
        return None
    return set([system["installer_id"]])


def _site_owners(kind, record):
    if kind == "site":
        return set([record["id"]])
    if kind == "load_calculation":
        return set([record["site_id"]])
    system = _system_for(kind, record)
    if system is None:
        return None
    return set([system["site_id"]])


def check_ownership(actor, kind, record):
    if actor.role == "CertifiedInstaller":
        owners = _installer_owners(kind, record)
    elif actor.role == "Homeowner":
        owners = _site_owners(kind, record)
    else:
        return record
    if owners is None:
        return record
    if actor.user_id not in owners:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Caller does not own the addressed resource.",
        )
    return record


# --------------------------------------------------------------------------- #
# Reference resolution
# --------------------------------------------------------------------------- #

def lookup(kind, ident):
    return store.get(TABLE_OF[kind], ident)


def ref(kind, ident):
    """Resolve a referenced resource or raise that entity's own 404."""
    record = lookup(kind, ident)
    if record is None:
        raise ApiError(
            NOT_FOUND_FOR_KIND[kind],
            "No %s with id %r." % (kind.replace("_", " "), ident),
        )
    return record


def path_ref(actor, kind, ident):
    """Resolve a path-addressed resource, then apply the ownership check."""
    record = ref(kind, ident)
    return check_ownership(actor, kind, record)
