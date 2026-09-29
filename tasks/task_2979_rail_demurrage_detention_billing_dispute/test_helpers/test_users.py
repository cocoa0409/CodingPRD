"""Auth header builders.

PRD 2.1 names the two headers explicitly: ``X-User-Role`` carries one of the
five recognised role names and ``X-User-ID`` carries the caller's identifier.
Every builder here goes through the framework's ``build_user_headers`` so that
the header names are written in exactly one place.

Identity discipline (PRD 2.1):

* A ``Customer``'s ``X-User-ID`` *is* the consignee's own ``id``, so the header
  can only be built once the consignee row exists - hence
  :func:`make_customer_headers`.
* A ``DemurrageAdjudicator``'s ``X-User-ID`` is the only user identifier the
  service persists, so distinct adjudicators must carry distinct, real,
  distinguishable values - hence :func:`make_adjudicator_headers` and the
  ``-a`` / ``-b`` naming convention used by the segregation-of-duties tests.
* ``RailroadAgent``, ``RegulatoryOfficer`` and ``BillingAdmin`` identifiers are
  opaque and are never persisted or compared, so fixed literals are fine.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ADJUDICATOR,
    ROLE_BILLING_ADMIN,
    ROLE_CUSTOMER,
    ROLE_RAILROAD_AGENT,
    ROLE_REGULATORY_OFFICER,
    UNDECLARED_ROLE,
)

# Opaque identifiers for the three roles whose ids are never persisted.
AGENT_USER_ID = "agent-001"
OFFICER_USER_ID = "officer-001"
ADMIN_USER_ID = "admin-001"

AGENT = build_user_headers(AGENT_USER_ID, ROLE_RAILROAD_AGENT)
OFFICER = build_user_headers(OFFICER_USER_ID, ROLE_REGULATORY_OFFICER)
ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_BILLING_ADMIN)


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for a ``Customer`` acting as the consignee ``customer_id``.

    PRD 2.1: "a ``Customer``'s user identifier *is* the consignee's ``id``".
    """
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def make_adjudicator_headers(adjudicator_id: str) -> Dict[str, str]:
    """Headers for a named ``DemurrageAdjudicator``.

    The identifier is persisted into ``first_level_adjudicator_id`` or
    ``appeal_adjudicator_id`` on begin-review, so it must be a real value that
    the segregation-of-duties bar can compare against.
    """
    return build_user_headers(adjudicator_id, ROLE_ADJUDICATOR)


def make_agent_headers(agent_id: str = AGENT_USER_ID) -> Dict[str, str]:
    return build_user_headers(agent_id, ROLE_RAILROAD_AGENT)


def make_officer_headers(officer_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(officer_id, ROLE_REGULATORY_OFFICER)


def make_admin_headers(admin_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(admin_id, ROLE_BILLING_ADMIN)


# ---------------------------------------------------------------------------
# Malformed-auth builders for PRD 2.8 bands 1 and 2.
# ---------------------------------------------------------------------------
def headers_without_role() -> Dict[str, str]:
    """No ``X-User-Role`` header at all."""
    return {"Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """``X-User-Role`` present but empty.

    The value is the empty string and not a run of spaces: a whitespace-only
    header value is a different (and invalid) HTTP construct.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_undeclared_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """A syntactically fine but undeclared role name."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A correct ``X-User-Role`` with no ``X-User-ID`` header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str) -> Dict[str, str]:
    """A correct ``X-User-Role`` with an empty ``X-User-ID``."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def adjudicator_pair(tag: str):
    """Two distinct, persistable adjudicator identities for one test.

    Returns ``(headers_a, id_a, headers_b, id_b)``.  The ``tag`` keeps the two
    identities distinguishable from every other test's pair, which matters
    because the round-1 identity is stored on the dispute and compared later.
    """
    id_a = "adj-%s-a" % tag
    id_b = "adj-%s-b" % tag
    return (
        make_adjudicator_headers(id_a),
        id_a,
        make_adjudicator_headers(id_b),
        id_b,
    )
