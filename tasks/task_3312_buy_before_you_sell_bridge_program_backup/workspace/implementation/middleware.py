"""Authentication and authorisation (PRD 2.1, validation priorities 1-2).

Every request carries two headers: ``X-User-ID`` identifies the acting party and
``X-User-Role`` declares the capacity in which that party is acting.  A request
that omits either header, or that names a role the system does not recognize, is
refused with ``ERR_UNAUTHENTICATED`` (401) before any business logic runs.  A
well-formed request whose role is not permitted on the target operation is
refused with ``ERR_UNAUTHORIZED`` (403).
"""

from flask import request

from constants import ENTITY_BACKED_ROLES, ROLES
from errors import (
    ERR_SOD_BACKUP_APPROVER,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ApiError,
)


class Actor:
    """The acting party resolved from the request headers."""

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in ENTITY_BACKED_ROLES

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Actor(%r, %r)" % (self.user_id, self.role)


def extract_actor():
    """Resolve the actor from headers, or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or user_id.strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED, "The X-User-ID header is required.")
    if role is None or role.strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED, "The X-User-Role header is required.")
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "The X-User-Role header names an unrecognized role.",
        )
    return Actor(user_id, role)


def require_role(actor, allowed):
    """Raise ERR_UNAUTHORIZED unless the actor's role is in ``allowed``."""
    if actor.role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "Role '%s' is not permitted on this operation." % actor.role,
        )


def check_segregation_of_duties(actor, offer):
    """The issuer of a backup offer may not be the operator that exercises it.

    PRD 2.1: segregation of duties applies to the backup guarantee, and this is
    the only place where two opaque operator identifiers are compared.
    """
    issuer = offer.get("issued_by")
    if issuer is None:
        return
    if actor.role not in ("Coordinator",):
        return
    if actor.user_id == issuer:
        raise ApiError(
            ERR_SOD_BACKUP_APPROVER,
            "The coordinator that issued this backup offer may not exercise it.",
        )


def assert_owner_or_operator(actor, owner_field_value):
    """Ownership check for entity-backed roles (PRD 2.1).

    When the actor's role is Homeowner or Agent, ``X-User-ID`` is the id of the
    acting entity and ownership checks compare the resource's foreign-key field
    to it.  Operational roles (Coordinator, Underwriter, ProgramAdmin) carry an
    opaque operator id that is never compared to an entity id, so they pass.
    """
    if not actor.is_entity_backed:
        return
    if owner_field_value is None:
        raise ApiError(ERR_UNAUTHORIZED, "This resource is not owned by the acting party.")
    if owner_field_value != actor.user_id:
        raise ApiError(ERR_UNAUTHORIZED, "This resource is not owned by the acting party.")