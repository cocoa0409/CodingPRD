"""Auth gate steps 1-4 (PRD 2.8), request scoping, and version finalisation."""

import functools

from flask import g, request

import db as store
from db import db
from errors import ApiError
import response as resp
from services import derive


def actor_id():
    return g.actor_id


def actor_role():
    return g.actor_role


def actor_account():
    """The CustomerAccount when the acting role is Customer, else None."""
    return getattr(g, "actor_account", None)


def endpoint(roles, mutating=False):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with store.LOCK:
                # 1. headers present and non-empty
                user_id = request.headers.get("X-User-ID")
                role = request.headers.get("X-User-Role")
                if user_id is None or user_id.strip() == "":
                    raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
                if role is None or role.strip() == "":
                    raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
                # 2. role is one of the five known roles
                if role not in store.ROLES:
                    raise ApiError("ERR_UNKNOWN_ROLE", "unknown role '%s'" % role)
                # 3. role authorised for this endpoint
                if role not in roles:
                    raise ApiError(
                        "ERR_FORBIDDEN_ROLE",
                        "role %s may not call this endpoint" % role,
                    )
                g.actor_id = user_id
                g.actor_role = role
                g.actor_account = None
                # 4. Customer identity resolves (only where Customer is authorised)
                if role == "Customer":
                    account = db.accounts.get(user_id)
                    if account is None:
                        raise ApiError(
                            "ERR_CUSTOMER_IDENTITY_UNKNOWN",
                            "X-User-ID does not resolve to a customer account",
                        )
                    g.actor_account = account
                if mutating:
                    store.begin_request()
                result = fn(**kwargs)
                if mutating:
                    derive.reconcile()
                    store.finalize_versions()
                return resp.build(result)

        return wrapper

    return decorator


def must_get(table, identifier, error_id):
    ent = table.get(identifier) if isinstance(identifier, str) else None
    if ent is None:
        raise ApiError(error_id, "referenced resource does not exist")
    return ent


def require_ownership(order):
    """Gate step 7 -- ERR_ORDER_NOT_OWNED, only for Customer actors."""
    if actor_role() == "Customer" and order["customer_id"] != actor_id():
        raise ApiError("ERR_ORDER_NOT_OWNED", "order belongs to another customer")
