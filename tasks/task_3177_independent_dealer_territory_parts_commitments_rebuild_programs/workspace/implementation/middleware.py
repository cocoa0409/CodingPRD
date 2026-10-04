"""Auth middleware: header extraction, role resolution and the ladder's
first three rungs (authentication, role permission, actor scope).
"""

from __future__ import annotations

from errors import (
    ApiError,
    E_DEALER_SCOPE_MISMATCH,
    E_UNAUTHENTICATED,
    E_UNAUTHORIZED,
)

DECLARED_ROLES = [
    "DealerNetworkManager",
    "DealerPerformanceReviewer",
    "PartsManager",
    "RebuildProgramSpecialist",
    "ServiceTechnicianSupervisor",
    "DealerSalesManager",
    "FinancePartner",
    "InputDealer",
]

ENTITY_BACKED_ROLES = {"DealerSalesManager": "Dealer", "InputDealer": "Dealer"}

# The two operations that consult a dealer scope at all (§2.1/§2.5 rung 3).
DEALER_SCOPE_OPERATIONS = {
    "POST /dealer-network/service-orders/{id}/begin",
    "POST /dealer-network/service-orders/{id}/record-emergency-fill",
}


class Actor:
    def __init__(self, role: str, user_id: str):
        self.role = role
        self.user_id = user_id

    @property
    def dealer_id(self):
        """The Dealer this actor is backed by, or None for an opaque operator."""
        if self.role in ENTITY_BACKED_ROLES:
            return self.user_id
        return None


def authenticate(headers, dealers_table) -> Actor:
    """Rung 1: both headers present, role declared, entity-backed id resolved."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError(E_UNAUTHENTICATED, "Both X-User-ID and X-User-Role are required.")
    if role not in DECLARED_ROLES:
        raise ApiError(E_UNAUTHENTICATED, "The acting role is not one of the declared roles.")
    if role in ENTITY_BACKED_ROLES:
        if user_id not in dealers_table:
            raise ApiError(E_UNAUTHENTICATED, "X-User-ID does not name a dealer.")
    return Actor(role, user_id)


def authorize(actor: Actor, permitted_roles) -> None:
    """Rung 2 (part one): the acting role must be permitted for the operation."""
    if actor.role not in permitted_roles:
        raise ApiError(E_UNAUTHORIZED, "The acting role is not permitted for this operation.")


def assert_dealer_scope(actor: Actor, resource_dealer_id) -> None:
    """Rung 2 (part two): an entity-backed actor may not act on another
    entity's resource.  Opaque operators are never compared to any entity id.
    """
    if actor.role == "ServiceTechnicianSupervisor":
        # §2.1 deliberate exception: the identifier is read but not compared to
        # the owning commitment's dealer_id.
        return
    scoped = actor.dealer_id
    if scoped is None:
        return
    if resource_dealer_id is not None and str(resource_dealer_id) != str(scoped):
        raise ApiError(E_UNAUTHORIZED, "An entity-backed actor may not act on another dealer's resources.")


def assert_technician_scope(actor: Actor, order_dealer_id) -> None:
    """Rung 3: only beginning service work and recording an emergency fill
    consult a dealer scope at all.
    """
    if actor.role != "ServiceTechnicianSupervisor":
        return
    # The technician supervisor's operator id is read but is not compared to
    # the order's dealer; the rung therefore always passes for this role and
    # only bites for an operator whose credentials cannot be resolved.
    if actor.user_id is None:
        raise ApiError(E_DEALER_SCOPE_MISMATCH, "The technician supervisor's scope does not cover this order.")