"""Ladder bands 1-4 of PRD §2.8: role-header authentication, user-identifier
authentication, role authorization and consignee ownership.

The identity headers are the ones PRD §2.1 names: `X-User-Role` carries the
acting role and `X-User-ID` carries the actor.
"""

from flask import request

from errors import fail

ROLE_CUSTOMER = "Customer"
ROLE_RAILROAD = "RailroadAgent"
ROLE_ADJUDICATOR = "DemurrageAdjudicator"
ROLE_REGULATOR = "RegulatoryOfficer"
ROLE_BILLING = "BillingAdmin"

ALL_ROLES = (
    ROLE_CUSTOMER,
    ROLE_RAILROAD,
    ROLE_ADJUDICATOR,
    ROLE_REGULATOR,
    ROLE_BILLING,
)

# The two roles whose user identifier drives an authorization decision, and
# whose absence is therefore an authentication failure rather than a schema one.
_USER_ID_REQUIRED = (ROLE_CUSTOMER, ROLE_ADJUDICATOR)


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER


def authenticate(*allowed_roles):
    """Bands 1-3, evaluated in that fixed order and short-circuiting."""
    # Band 1 - role-header authentication.  Runs before any path parameter is
    # resolved, so an unauthenticated request to a bogus id returns 401.
    raw_role = request.headers.get("X-User-Role")
    if raw_role is None or raw_role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = raw_role.strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")

    # Band 2 - user-identifier authentication for the two roles that need it.
    raw_uid = request.headers.get("X-User-ID")
    user_id = raw_uid if raw_uid is not None else None
    if role in _USER_ID_REQUIRED:
        if user_id is None or user_id.strip() == "":
            fail("ERR_UNAUTHENTICATED", "X-User-ID header is required for this role.")

    # Band 3 - role authorization, before any existence check.
    if role not in allowed_roles:
        fail("ERR_ROLE_FORBIDDEN", "Role %s may not perform this operation." % role)

    return Actor(role, user_id)


def require_owner(actor, owner_customer_id):
    """Band 4 - consignee ownership on a specific resource."""
    if actor.role != ROLE_CUSTOMER:
        return
    if owner_customer_id != actor.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting consignee does not own this resource.")


def segregation_bar(actor, dispute):
    """Band 5 - the first-level adjudicator may not act on round two."""
    if dispute.get("round_number", 1) >= 2:
        first = dispute.get("first_level_adjudicator_id")
        if first is not None and first == actor.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")
