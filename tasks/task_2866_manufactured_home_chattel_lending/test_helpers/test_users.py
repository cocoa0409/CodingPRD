"""Pre-built role headers for the seven roles the PRD declares (PRD §2.1).

Identity semantics differ by role, and the difference decides what
``X-User-ID`` is compared against:

* ``PlatformAdmin``, ``CreditAnalyst``, ``ClosingAgent``, ``Servicer`` and
  ``RecoveryManager`` carry an opaque operator identifier that is never
  compared to any entity's ``id``.  The shared constants below are the
  canonical form for those roles.  Where an operator identity is itself part of
  the assertion — the certifier of a valuation versus the approver of the loan
  it secures — use the per-identity builders so the two identifiers are chosen
  deliberately.
* ``CommunityOperator`` carries the ``id`` of the acting Community and
  ``Borrower`` carries the ``id`` of the acting Borrower.  For those two roles
  the per-instance builder is mandatory: a shared constant can never equal a
  real entity's ``id``, so every ownership check would refuse every request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Distinct operator identities used where segregation of duties is in play.
VALUATION_CERTIFIER_USER_ID = "analyst-val-01"
LOAN_APPROVER_USER_ID = "analyst-uw-02"
RECOVERY_CERTIFIER_USER_ID = "recovery-val-07"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers("admin-ops-01", "PlatformAdmin"),
    "credit_analyst_headers": build_user_headers("analyst-uw-02", "CreditAnalyst"),
    "closing_agent_headers": build_user_headers("closer-01", "ClosingAgent"),
    "servicer_headers": build_user_headers("servicer-01", "Servicer"),
    "recovery_manager_headers": build_user_headers("recovery-01", "RecoveryManager"),
    # Fallbacks for the two identity-backed roles: valid headers whose
    # X-User-ID intentionally names no entity, so they are only ever used where
    # ownership is not what the test is about (or where refusal is expected).
    "community_operator_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000c0", "CommunityOperator"
    ),
    "borrower_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000b0", "Borrower"
    ),
}


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named PlatformAdmin operator identity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_credit_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named CreditAnalyst operator identity.

    The identity matters at valuation certification (recorded as
    ``certified_by_user_id``) and at loan approval (recorded as
    ``approved_by_user_id``).
    """
    return build_user_headers(user_id, "CreditAnalyst")


def make_closing_agent_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named ClosingAgent operator identity."""
    return build_user_headers(user_id, "ClosingAgent")


def make_servicer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named Servicer operator identity."""
    return build_user_headers(user_id, "Servicer")


def make_recovery_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named RecoveryManager operator identity."""
    return build_user_headers(user_id, "RecoveryManager")


def make_community_operator_headers(community_id: str) -> Dict[str, str]:
    """Headers for a CommunityOperator acting on its own community.

    ``X-User-ID`` must be the acting Community's own ``id``.
    """
    return build_user_headers(community_id, "CommunityOperator")


def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """Headers for a Borrower reading its own portfolio.

    ``X-User-ID`` must be the acting Borrower's own ``id``.
    """
    return build_user_headers(borrower_id, "Borrower")


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Well-formed headers carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Well-formed headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
