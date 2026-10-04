"""Route package: auth, per-role enforcement and blueprint registration."""

from flask import request

from common import identity
from errors import ApiError
from response import read_pagination

BLUEPRINT_MODULES = (
    "routes.config",
    "routes.performances",
    "routes.patrons",
    "routes.draws",
    "routes.queueing",
    "routes.purchases",
    "routes.refunds",
    "routes.exchanges",
    "routes.inventory",
    "routes.handoffs",
)


def actor(allowed_roles):
    """Rungs one and two: identity first, then permission."""
    user_id, role = identity(request)
    if user_id is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN")
    return user_id, role


def active_performer(allowed_roles):
    """Identity and permission only; no patron-entitlement role restriction."""
    return actor(allowed_roles)


def pagination():
    from flask import request as _request

    parsed = read_pagination(_request.args)
    if parsed is None:
        raise ApiError("ERR_INVALID_STATE", "Invalid limit or offset.")
    return parsed


def payload():
    from flask import request as _request

    return _request.get_json(silent=True) or {}


def register_all(app):
    from importlib import import_module

    for module_name in BLUEPRINT_MODULES:
        module = import_module(module_name)
        app.register_blueprint(module.bp)