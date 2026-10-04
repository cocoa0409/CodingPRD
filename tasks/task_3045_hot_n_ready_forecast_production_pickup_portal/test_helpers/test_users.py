"""Caller identities.

All four roles carry an opaque ``X-User-ID`` that the server never compares to a
persisted entity id; the only ownership rule is that a ``Customer`` caller's
``X-User-ID`` must equal the ``customer_id`` recorded on the target order for
order-scoped calls.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CREW_MEMBER,
    ROLE_CUSTOMER,
    ROLE_SHIFT_LEAD,
    ROLE_STORE_MANAGER,
    Headers,
)

STORE_MANAGER_USER_ID = "store-manager-operator-001"
SHIFT_LEAD_USER_ID = "shift-lead-operator-001"
CREW_MEMBER_USER_ID = "crew-member-operator-001"

TEST_USERS = {
    ROLE_STORE_MANAGER: {"user_id": STORE_MANAGER_USER_ID, "role": ROLE_STORE_MANAGER},
    ROLE_SHIFT_LEAD: {"user_id": SHIFT_LEAD_USER_ID, "role": ROLE_SHIFT_LEAD},
    ROLE_CREW_MEMBER: {"user_id": CREW_MEMBER_USER_ID, "role": ROLE_CREW_MEMBER},
}


def make_manager_headers() -> Headers:
    """Headers for the store manager."""
    return build_user_headers(STORE_MANAGER_USER_ID, ROLE_STORE_MANAGER)


def make_shift_lead_headers() -> Headers:
    """Headers for the shift lead."""
    return build_user_headers(SHIFT_LEAD_USER_ID, ROLE_SHIFT_LEAD)


def make_crew_headers() -> Headers:
    """Headers for a crew member."""
    return build_user_headers(CREW_MEMBER_USER_ID, ROLE_CREW_MEMBER)


def make_customer_headers(customer_id: str) -> Headers:
    """Headers for a portal customer.

    For order-scoped calls (pay, claim, cancel) the ``X-User-ID`` must equal the
    ``customer_id`` recorded on the order at creation, so always pass the owning
    customer handle here.
    """
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def headers_without_identity() -> Headers:
    """A request that carries no identity headers at all."""
    return {"Content-Type": "application/json"}


__all__ = [
    "STORE_MANAGER_USER_ID",
    "SHIFT_LEAD_USER_ID",
    "CREW_MEMBER_USER_ID",
    "TEST_USERS",
    "make_manager_headers",
    "make_shift_lead_headers",
    "make_crew_headers",
    "make_customer_headers",
    "headers_without_identity",
]
