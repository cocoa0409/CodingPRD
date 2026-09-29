"""Validation ladder rungs 1-4 (PRD 2.1, 2.5)."""
from flask import request

from errors import raise_error

ROLES = (
    "ShopAdmin",
    "Estimator",
    "PartsManager",
    "Technician",
    "QcInspector",
    "InsurerAdjuster",
    "Customer",
)

ENTITY_BACKED = ("InsurerAdjuster", "Customer")


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_insurer(self):
        return self.role == "InsurerAdjuster"

    @property
    def is_customer(self):
        return self.role == "Customer"

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        raise_error("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise_error("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)


def own_order(actor, order):
    """Rung 3: entity-backed roles may only reach their own repair order."""
    if order is None:
        return
    if actor.is_insurer and order.get("insurer_id") != actor.user_id:
        raise_error("ERR_NOT_RESOURCE_OWNER")
    if actor.is_customer and order.get("customer_id") != actor.user_id:
        raise_error("ERR_NOT_RESOURCE_OWNER")


def owns(actor, order):
    if order is None:
        return False
    if actor.is_insurer:
        return order.get("insurer_id") == actor.user_id
    if actor.is_customer:
        return order.get("customer_id") == actor.user_id
    return True


def segregation(actor, order):
    """Rung 4: the estimator who blueprinted may not inspect."""
    if order is None:
        return
    if order.get("blueprint_by_user_id") is not None \
            and order["blueprint_by_user_id"] == actor.user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES")
